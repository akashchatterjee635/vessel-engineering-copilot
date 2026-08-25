"""
Vessel Engineering Copilot — full orchestrator (v5 with MCP + CEMG + LLMOps + Guardrails + Prometheus)

Covers:
1. FastMCP Remote Server Integration (Streamable HTTP transport).
2. Input and Output Guardrails (Safety overrides & warning check).
3. Advanced RAG (Document search in manual pages).
4. Persistent SQLite Checkpointing (LangGraph SqliteSaver).
5. CEMG Causal Experience Memory (tool peeking, storing outcomes, cooldowns).
6. LLMOps logging (token count, cost estimations, and latency logging).
7. Prometheus metrics instrumentation.
"""

import asyncio
import json
import logging
import os
import time
import uuid
import sqlite3
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, Dict, List, Literal, Optional

import aiosqlite
import tiktoken
import yaml
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from pydantic import BaseModel
from typing_extensions import TypedDict

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server as prom_start
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

try:
    from fastmcp import Client as MCPClient
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False

import db

# CEMG memory imports
from cemg.storage import SqliteStorage
from cemg.memory import build_memory_block, peek_signature_status, store_experience

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("VESSEL_COPILOT_DB", "vessel_copilot.db")
CHECKPOINTS_DB_PATH = os.environ.get("VESSEL_COPILOT_CHECKPOINTS_DB", "vessel_checkpoints.db")
OPENAI_MODEL = os.environ.get("VESSEL_COPILOT_MODEL", "gpt-4.1")
MCP_SERVERS_ENABLED = os.environ.get("MCP_SERVERS_ENABLED", "false").lower() == "true"

# --- 0. Model Config (from YAML if present) ---
_CONFIG_PATH = os.environ.get("MODEL_CONFIG_PATH", "mlops/model_config.yaml")
_config: Dict[str, Any] = {}
if os.path.exists(_CONFIG_PATH):
    with open(_CONFIG_PATH, "r") as f:
        _config = yaml.safe_load(f) or {}

# ATEX thresholds from config or defaults
_guardrail_cfg = _config.get("guardrails", {}).get("output", {})
ATEX_WARNING_THRESHOLD = _guardrail_cfg.get("atex_lel_advisory_threshold", 10.0)
ATEX_CRITICAL_THRESHOLD = _guardrail_cfg.get("atex_lel_critical_threshold", 20.0)

# --- 1. CEMG Initialization ---
CEMG_DB_PATH = os.environ.get("CEMG_SQLITE_PATH", "cemg_memory.db")
cemg_storage = SqliteStorage(db_path=CEMG_DB_PATH)


# --- 1b. Prometheus Metrics ---
if PROMETHEUS_AVAILABLE and _config.get("feature_flags", {}).get("prometheus_enabled", False):
    LLM_CALL_COUNTER = Counter("copilot_llm_calls_total", "Total LLM API invocations", ["node_name"])
    LLM_TOKEN_COUNTER = Counter("copilot_llm_tokens_total", "Total LLM tokens consumed", ["token_type"])
    LLM_COST_COUNTER = Counter("copilot_llm_cost_dollars", "Estimated LLM API cost in USD")
    TOOL_LATENCY_HISTOGRAM = Histogram("copilot_tool_latency_seconds", "MCP tool execution latency", ["tool_name"], buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
    GUARDRAIL_BLOCK_COUNTER = Counter("copilot_guardrail_blocks_total", "Total guardrail blocks", ["guardrail_type"])
    ATEX_ALERT_COUNTER = Counter("copilot_atex_alerts_total", "Total ATEX alerts raised", ["severity"])
    CEMG_FAILURE_COUNTER = Counter("copilot_cemg_failures_total", "Tools blocked or failed via CEMG", ["tool_name"])
    ACTIVE_THREADS_GAUGE = Gauge("copilot_active_threads", "Number of active conversation threads")
    _PROM_ENABLED = True
    # Start Prometheus metrics HTTP server on port 9090
    try:
        prom_start(9090)
        logger.info("Prometheus metrics server started on :9090")
    except OSError:
        logger.warning("Prometheus metrics port 9090 already in use, skipping")
else:
    _PROM_ENABLED = False


# --- 1c. MCP Client Manager ---

class MCPClientManager:
    """Manages connections to FastMCP remote servers over Streamable HTTP transport.
    
    Each MCP server is identified by a name (e.g., 'telemetry', 'compliance').
    Connection URLs are configured via environment variables or model_config.yaml.
    """
    
    # Default server URL map
    DEFAULT_URLS = {
        "telemetry": "http://localhost:8001/mcp",
        "compliance": "http://localhost:8002/mcp",
        "history": "http://localhost:8003/mcp",
        "weather": "http://localhost:8004/mcp",
        "port_services": "http://localhost:8005/mcp",
    }
    
    # Environment variable overrides
    ENV_MAP = {
        "telemetry": "MCP_TELEMETRY_URL",
        "compliance": "MCP_COMPLIANCE_URL",
        "history": "MCP_HISTORY_URL",
        "weather": "MCP_WEATHER_URL",
        "port_services": "MCP_PORT_SERVICES_URL",
    }
    
    def __init__(self):
        self._urls: Dict[str, str] = {}
        self._load_urls()
    
    def _load_urls(self):
        """Load server URLs from config, environment, or defaults."""
        mcp_cfg = _config.get("mcp_servers", {})
        for name, default_url in self.DEFAULT_URLS.items():
            # Priority: env var > yaml config > default
            env_url = os.environ.get(self.ENV_MAP[name])
            cfg_url = mcp_cfg.get(name, {}).get("url") if isinstance(mcp_cfg.get(name), dict) else None
            self._urls[name] = env_url or cfg_url or default_url
    
    def get_url(self, server_name: str) -> str:
        """Get the URL for a named MCP server."""
        return self._urls.get(server_name, self.DEFAULT_URLS.get(server_name, ""))
    
    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on a remote FastMCP server.
        
        Args:
            server_name: The MCP server identifier (e.g., 'telemetry', 'compliance')
            tool_name: The tool function name on that server (e.g., 'get_machinery_telemetry')
            arguments: Keyword arguments to pass to the tool
        
        Returns:
            The tool's return value as a dict.
        
        Raises:
            ConnectionError: If the MCP server is unreachable.
            RuntimeError: If the tool call fails.
        """
        if not FASTMCP_AVAILABLE:
            raise ImportError("fastmcp is not installed. Install with: pip install fastmcp")
        
        url = self.get_url(server_name)
        logger.debug(f"MCP call: {server_name}/{tool_name} -> {url}")
        
        async with MCPClient(url) as client:
            result = await client.call_tool(tool_name, arguments)
            # FastMCP returns content as a list of content blocks; extract text
            if hasattr(result, '__iter__'):
                for item in result:
                    if hasattr(item, 'text'):
                        return json.loads(item.text)
            return result


# Global MCP client manager instance
mcp_manager = MCPClientManager()


# --- 2. Token & Cost Counters ---
def count_tokens(text: str, model: str = "gpt-4") -> int:
    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


# --- 3. State contracts ---

class TriageDecision(BaseModel):
    interaction_type: Literal[
        "diagnostic", "logbook_entry", "onboarding_check",
        "port_assistance", "checklist_request", "informational",
    ]
    urgency: Literal["routine", "elevated", "urgent"]
    equipment_hint: Optional[str] = None
    needs_telemetry: bool = False
    needs_compliance_lookup: bool = False
    needs_historical_rag: bool = False
    needs_weather_voyage: bool = False
    needs_maps: bool = False
    confidence: float
    reasoning: str


class AgentState(TypedDict, total=False):
    tenant_id: str
    vessel_id: str
    vessel_class: str
    thread_id: str
    turn_id: str
    engineer_id: str
    user_query: str

    triage_decision: Optional[Dict[str, Any]]
    equipment_record: Optional[Dict[str, Any]]

    atex_alert: Optional[Dict[str, Any]]

    telemetry_data: Optional[Dict[str, Any]]
    compliance_data: Optional[Dict[str, Any]]
    historical_rag_data: Optional[Dict[str, Any]]
    weather_voyage_data: Optional[Dict[str, Any]]
    maps_data: Optional[Dict[str, Any]]

    # Advanced RAG, Guardrails, and CEMG state fields:
    rag_documents: Optional[List[Dict[str, Any]]]
    guardrail_violation: Optional[str]
    output_guardrail_applied: Optional[bool]
    cemg_memory_context: Optional[str]
    decision_snapshots: Optional[List[Dict[str, Any]]]

    logbook_result: Optional[Dict[str, Any]]
    onboarding_result: Optional[Dict[str, Any]]
    checklist_result: Optional[Dict[str, Any]]
    final_synthesis: Optional[Dict[str, Any]]
    work_order_created: Optional[bool]

    audit_records: List[Dict[str, Any]]


# --- 4. LLM clients and Wrappers ---

_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)
_triage_llm = _llm.with_structured_output(TriageDecision)

TRIAGE_SYSTEM_PROMPT = """You are the triage router for a marine engineering copilot used by
ship's crew. Classify the crew member's message into exactly one interaction_type:
- diagnostic: crew describes a symptom/problem and wants help diagnosing it
- logbook_entry: crew is reporting maintenance/work done or an observation to log, not asking a question
- onboarding_check: crew wants to know what's different on this vessel vs what they're used to
- port_assistance: crew needs help related to docking, port operations, weather, or logistics
- checklist_request: crew wants a maintenance/condition-monitoring checklist
- informational: general question not tied to a specific live issue

Extract equipment_hint as the crew's own words for the machine/system involved, if any is
mentioned (e.g. "aux boiler feed pump", "ballast valve"). Leave null if none mentioned.

Be conservative about which data sources you request — each one costs a real tool call.
Only request a source if the query cannot reasonably be answered without it."""


async def call_llm_with_audit(
    node_name: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    structured_schema: Optional[Any] = None,
    confidence_score: float = 1.0
) -> tuple[Any, Dict[str, Any]]:
    start = time.perf_counter()
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    if structured_schema:
        extractor = _llm.with_structured_output(structured_schema)
        response = await extractor.ainvoke(messages)
        response_text = json.dumps(response.model_dump() if hasattr(response, "model_dump") else response.__dict__)
    else:
        response = await _llm.ainvoke(messages)
        response_text = response.content
    
    latency_ms = int((time.perf_counter() - start) * 1000)
    
    _model_cfg = _config.get("model", {})
    cost_prompt = _model_cfg.get("cost_per_million_prompt_tokens", 2.5)
    cost_completion = _model_cfg.get("cost_per_million_completion_tokens", 10.0)
    
    prompt_str = (system_prompt or "") + "\n" + prompt
    prompt_tokens = count_tokens(prompt_str)
    completion_tokens = count_tokens(response_text)
    cost = (prompt_tokens * cost_prompt + completion_tokens * cost_completion) / 1_000_000.0
    
    # Prometheus instrumentation
    if _PROM_ENABLED:
        LLM_CALL_COUNTER.labels(node_name=node_name).inc()
        LLM_TOKEN_COUNTER.labels(token_type="prompt").inc(prompt_tokens)
        LLM_TOKEN_COUNTER.labels(token_type="completion").inc(completion_tokens)
        LLM_COST_COUNTER.inc(cost)
    
    audit_rec = {
        "agent_name": node_name,
        "gate_fired": 1,
        "gate_reasoning": f"LLM execution in {node_name}",
        "confidence_score": confidence_score,
        "tool_name": "openai_llm",
        "input_payload": json.dumps({"prompt": prompt[:500]}),
        "output_payload": response_text,
        "latency_ms": latency_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost": cost,
        "is_used_by_synthesis": 1 if node_name != "TriageRouter" else 0
    }
    
    return response, audit_rec


# --- 5. Tool execution wrapped with CEMG ---

async def execute_tool_with_cemg(tool_name: str, coro_factory, params: dict, state: AgentState) -> Dict[str, Any]:
    engineer_id = state["engineer_id"]
    tenant_id = state["tenant_id"]
    turn_id = state["turn_id"]
    
    # 1. Peek signature status
    sig_status = peek_signature_status(cemg_storage, agent_id=engineer_id, tool=tool_name, params=params, task_namespace=tenant_id)
    
    # Track decision snapshot
    if "decision_snapshots" not in state:
        state["decision_snapshots"] = []
    state["decision_snapshots"].append({
        "tool": tool_name,
        "params": params,
        "action_signature": sig_status["action_signature"],
        "status_before": sig_status["status_before"]
    })
    
    start = time.perf_counter()
    try:
        # Simulate connection/execution failures for testing
        if tool_name == "telemetry_mcp" and params.get("equipment_id") == "equip-failed-telemetry":
            raise ConnectionError("Telemetry connection timed out (sensor offline).")
            
        res = await coro_factory()
        latency_ms = int((time.perf_counter() - start) * 1000)
        
        # Prometheus: record tool latency
        if _PROM_ENABLED:
            TOOL_LATENCY_HISTOGRAM.labels(tool_name=tool_name).observe(latency_ms / 1000.0)
        
        # Store success experience in CEMG
        store_experience(
            driver=cemg_storage,
            agent_id=engineer_id,
            session_id=turn_id,
            action=f"Invoke tool {tool_name} with params {json.dumps(params)}",
            outcome="success",
            tool=tool_name,
            params=params,
            task_namespace=tenant_id
        )
        return {"status": "success", "data": res, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        
        # Prometheus: record tool failure
        if _PROM_ENABLED:
            TOOL_LATENCY_HISTOGRAM.labels(tool_name=tool_name).observe(latency_ms / 1000.0)
            CEMG_FAILURE_COUNTER.labels(tool_name=tool_name).inc()
        
        # Store failure experience in CEMG
        store_experience(
            driver=cemg_storage,
            agent_id=engineer_id,
            session_id=turn_id,
            action=f"Invoke tool {tool_name} with params {json.dumps(params)}",
            outcome="failure",
            observed_error=str(e),
            reasoning=f"Tool {tool_name} execution failed due to exception.",
            tool=tool_name,
            params=params,
            task_namespace=tenant_id
        )
        return {"status": "failed", "data": {"error": str(e)}, "latency_ms": latency_ms}


# --- 6. Tool / MCP Functions ---
#
# When MCP_SERVERS_ENABLED=true, tools call remote FastMCP servers.
# When false (default), they fall back to local mock/stub implementations.
#

# --- 6a. Local mock fallbacks (used when MCP is disabled) ---

async def _mock_telemetry(tenant_id: str, vessel_id: str, equipment_id: Optional[str]) -> Dict[str, Any]:
    await asyncio.sleep(0.3)
    return {"equipment_id": equipment_id, "vibration_amplitude": 6.8, "frequency_band": "high",
            "gas_reading_pct_lel": 4.2}


async def _mock_compliance(tenant_id: str, vessel_id: str) -> Dict[str, Any]:
    await asyncio.sleep(0.4)
    return {"rule_set": "DNV-GL-Part-4", "status": "Compliant"}


async def _mock_historical_rag(equipment_id: Optional[str]) -> Dict[str, Any]:
    if not equipment_id:
        return {"previous_logs": []}
    logs = await db.get_equipment_log_history(equipment_id)
    return {"previous_logs": logs}


async def _mock_weather_voyage(vessel_id: str) -> Dict[str, Any]:
    await asyncio.sleep(0.5)
    return {"wave_height_meters": 2.1, "wind_kn": 14}


async def _mock_maps(vessel_id: str) -> Dict[str, Any]:
    await asyncio.sleep(0.3)
    return {"nearest_port_services": ["bunkering", "spare parts depot"], "berth_eta_hint": "port context stub"}


# --- 6b. MCP-backed tool functions ---

async def run_telemetry(tenant_id: str, vessel_id: str, equipment_id: Optional[str]) -> Dict[str, Any]:
    """Fetch machinery telemetry from the MCP telemetry server or local mock."""
    if MCP_SERVERS_ENABLED:
        return await mcp_manager.call_tool("telemetry", "get_machinery_telemetry", {
            "vessel_id": vessel_id, "equipment_id": equipment_id or ""
        })
    return await _mock_telemetry(tenant_id, vessel_id, equipment_id)


async def run_gas_hazard(vessel_id: str, equipment_id: str) -> Dict[str, Any]:
    """Fetch gas hazard status from MCP telemetry server (ATEX checks)."""
    if MCP_SERVERS_ENABLED:
        return await mcp_manager.call_tool("telemetry", "get_gas_hazard_status", {
            "vessel_id": vessel_id, "equipment_id": equipment_id
        })
    # Fallback: use the general telemetry mock which includes gas_reading_pct_lel
    return await _mock_telemetry("", vessel_id, equipment_id)


async def run_compliance(tenant_id: str, vessel_id: str) -> Dict[str, Any]:
    """Verify class compliance via MCP compliance server or local mock."""
    if MCP_SERVERS_ENABLED:
        return await mcp_manager.call_tool("compliance", "verify_class_compliance", {
            "vessel_id": vessel_id, "system_category": "rotating_machinery"
        })
    return await _mock_compliance(tenant_id, vessel_id)


async def run_historical_rag(equipment_id: Optional[str]) -> Dict[str, Any]:
    """Retrieve equipment maintenance history via MCP history server or local DB."""
    if MCP_SERVERS_ENABLED and equipment_id:
        return await mcp_manager.call_tool("history", "get_equipment_history", {
            "equipment_id": equipment_id, "limit": 10
        })
    return await _mock_historical_rag(equipment_id)


async def run_weather_voyage(vessel_id: str) -> Dict[str, Any]:
    """Get marine weather conditions via MCP weather server or local mock."""
    if MCP_SERVERS_ENABLED:
        return await mcp_manager.call_tool("weather", "get_marine_weather", {
            "vessel_id": vessel_id
        })
    return await _mock_weather_voyage(vessel_id)


async def run_maps(vessel_id: str) -> Dict[str, Any]:
    """Get port services data via MCP port services server or local mock."""
    if MCP_SERVERS_ENABLED:
        return await mcp_manager.call_tool("port_services", "get_port_services", {
            "vessel_id": vessel_id
        })
    return await _mock_maps(vessel_id)


# --- 7. Nodes ---

async def input_guardrail_node(state: AgentState) -> Dict[str, Any]:
    query = state["user_query"].lower()
    violation = None
    
    # Load bypass keywords from config or use defaults
    bypass_keywords = _config.get("guardrails", {}).get("input", {}).get(
        "bypass_keywords", ["override", "bypass", "disable safety", "force", "ignore protocol"]
    )
    trigger_phrases = ["bypass safety", "override gas sensor", "ignore atex", "force override"] + [
        kw.lower() for kw in bypass_keywords
    ]
    
    if any(keyword in query for keyword in trigger_phrases):
        violation = "Safety override attempt blocked. Operations cannot be bypassed or forced without ATEX validation."
        if _PROM_ENABLED:
            GUARDRAIL_BLOCK_COUNTER.labels(guardrail_type="input").inc()
        
    return {"guardrail_violation": violation, "audit_records": []}


def route_input_guardrail(state: AgentState) -> str:
    if state.get("guardrail_violation"):
        return "SynthesisAgent"
    return "TriageRouter"


async def triage_router_node(state: AgentState) -> Dict[str, Any]:
    turn_id = str(uuid.uuid4())
    engineer_id = state["engineer_id"]
    tenant_id = state["tenant_id"]
    
    # Retrieve CEMG context block to inform triage/routing decisions
    cemg_context = build_memory_block(
        cemg_storage,
        agent_id=engineer_id,
        query_action=state["user_query"],
        task_namespace=tenant_id
    )
    
    system_prompt = TRIAGE_SYSTEM_PROMPT
    if cemg_context:
        system_prompt += f"\n\n{cemg_context}"
        
    decision, audit_rec = await call_llm_with_audit(
        "TriageRouter",
        state["user_query"],
        system_prompt=system_prompt,
        structured_schema=TriageDecision
    )
    
    audit_rec["turn_id"] = turn_id
    
    return {
        "triage_decision": decision.model_dump(),
        "turn_id": turn_id,
        "audit_records": [audit_rec],
        "cemg_memory_context": cemg_context
    }


async def resolve_equipment_node(state: AgentState) -> Dict[str, Any]:
    hint = state["triage_decision"]["equipment_hint"]
    record = await db.resolve_equipment(state["vessel_id"], hint)
    return {"equipment_record": record}


async def document_retriever_node(state: AgentState) -> Dict[str, Any]:
    equipment = state.get("equipment_record")
    vessel_class = state["vessel_class"]
    equipment_id = equipment["id"] if equipment else None
    
    docs = await db.search_documents(vessel_class, equipment_id, state["user_query"])
    return {"rag_documents": docs}


async def atex_hazard_check_node(state: AgentState) -> Dict[str, Any]:
    equipment = state.get("equipment_record")
    if not equipment or not equipment.get("is_atex_zone"):
        return {"atex_alert": None}

    # Use dedicated gas hazard tool for ATEX checks when MCP is enabled
    if MCP_SERVERS_ENABLED:
        try:
            reading = await run_gas_hazard(state["vessel_id"], equipment["id"])
        except Exception:
            # Fallback to general telemetry if gas-specific endpoint fails
            reading = await run_telemetry(state["tenant_id"], state["vessel_id"], equipment["id"])
    else:
        reading = await run_telemetry(state["tenant_id"], state["vessel_id"], equipment["id"])
    
    lel_pct = reading.get("gas_reading_pct_lel", 0.0)

    if lel_pct >= ATEX_CRITICAL_THRESHOLD:
        severity = "critical"
    elif lel_pct >= ATEX_WARNING_THRESHOLD:
        severity = "warning"
    else:
        severity = "advisory"

    # Prometheus: track ATEX alert
    if _PROM_ENABLED and severity in ("warning", "critical"):
        ATEX_ALERT_COUNTER.labels(severity=severity).inc()

    alert = {
        "equipment_id": equipment["id"],
        "equipment_name": equipment["name"],
        "zone_class": equipment["atex_zone_class"],
        "reading": reading,
        "severity": severity,
    }

    if severity in ("warning", "critical"):
        await db.insert_atex_event(
            event_id=str(uuid.uuid4()), tenant_id=state["tenant_id"], vessel_id=state["vessel_id"],
            equipment_id=equipment["id"], thread_id=state["thread_id"],
            zone_class=equipment["atex_zone_class"], trigger_reading=reading, severity=severity,
        )

    return {"atex_alert": alert}


def route_by_interaction(state: AgentState) -> str:
    return {
        "logbook_entry": "LogbookExtractionAgent",
        "onboarding_check": "VesselCompatibilityAgent",
        "checklist_request": "ChecklistAgent",
    }.get(state["triage_decision"]["interaction_type"], "FanOutOrchestrator")


async def fan_out_orchestrator(state: AgentState) -> Dict[str, Any]:
    decision = TriageDecision(**state["triage_decision"])
    tenant_id, vessel_id = state["tenant_id"], state["vessel_id"]
    equipment_id = state.get("equipment_record", {}).get("id") if state.get("equipment_record") else None
    
    if "decision_snapshots" not in state:
        state["decision_snapshots"] = []

    mapping = [
        ("needs_telemetry", "telemetry_data", "telemetry_mcp", 
         {"vessel_id": vessel_id, "equipment_id": equipment_id},
         partial(run_telemetry, tenant_id, vessel_id, equipment_id)),
        ("needs_compliance_lookup", "compliance_data", "compliance_mcp", 
         {"vessel_id": vessel_id},
         partial(run_compliance, tenant_id, vessel_id)),
        ("needs_historical_rag", "historical_rag_data", "historical_rag", 
         {"equipment_id": equipment_id},
         partial(run_historical_rag, equipment_id)),
        ("needs_weather_voyage", "weather_voyage_data", "marine_weather_api", 
         {"vessel_id": vessel_id},
         partial(run_weather_voyage, vessel_id)),
        ("needs_maps", "maps_data", "maps_api", 
         {"vessel_id": vessel_id},
         partial(run_maps, vessel_id)),
    ]

    tasks, task_meta, audit_records = [], [], []
    for gate_flag, context_key, tool_name, params, coro_factory in mapping:
        if getattr(decision, gate_flag):
            tasks.append(execute_tool_with_cemg(tool_name, coro_factory, params, state))
            task_meta.append((context_key, tool_name, params))
        else:
            audit_records.append({
                "agent_name": context_key, "gate_fired": 0, "gate_reasoning": decision.reasoning,
                "confidence_score": decision.confidence, "tool_name": tool_name,
                "input_payload": "{}", "output_payload": None, "latency_ms": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0.0
            })

    results = await asyncio.gather(*tasks) if tasks else []
    updated_state: Dict[str, Any] = {}
    
    updated_state["decision_snapshots"] = state["decision_snapshots"]
    
    for (context_key, tool_name, params), wrapper in zip(task_meta, results):
        updated_state[context_key] = wrapper["data"] if wrapper["status"] == "success" else None
        audit_records.append({
            "agent_name": context_key, "gate_fired": 1, "gate_reasoning": decision.reasoning,
            "confidence_score": decision.confidence, "tool_name": tool_name,
            "input_payload": json.dumps(params),
            "output_payload": json.dumps(wrapper["data"]), "latency_ms": wrapper["latency_ms"],
            "prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0.0
        })

    updated_state["audit_records"] = state.get("audit_records", []) + audit_records
    return updated_state


async def synthesis_agent(state: AgentState) -> Dict[str, Any]:
    if state.get("guardrail_violation"):
        return {
            "final_synthesis": {
                "evaluation": f"GUARDRAIL BLOCKED: {state['guardrail_violation']}",
                "sources_used": []
            }
        }
        
    used_keys = [k for k in ("telemetry_data", "compliance_data", "historical_rag_data",
                              "weather_voyage_data", "maps_data") if state.get(k) is not None]
    audit_records = state.get("audit_records", [])
    for rec in audit_records:
        rec["is_used_by_synthesis"] = 1 if rec["agent_name"] in used_keys else rec.get("is_used_by_synthesis", 0)

    atex_note = ""
    if state.get("atex_alert") and state["atex_alert"]["severity"] != "advisory":
        a = state["atex_alert"]
        atex_note = f"\n\nSAFETY ALERT ({a['severity'].upper()}): {a['equipment_name']} is in {a['zone_class']} — gas reading {a['reading']['gas_reading_pct_lel']}% LEL. Follow ATEX zone protocol before proceeding."

    rag_docs_text = ""
    docs = state.get("rag_documents", [])
    if docs:
        rag_docs_text = "\n\nRetrieved Manual Pages:\n" + "\n".join([f"- [{d['title']}]: {d['content']}" for d in docs])

    cemg_context = state.get("cemg_memory_context", "")
    cemg_context_text = f"\n\n{cemg_context}" if cemg_context else ""

    prompt = f"""Given this vessel engineering context, produce a concise, practical assessment
for a crew member (not a manual excerpt — plain, direct guidance). Reference which data
sources informed the assessment.

Query: {state['user_query']}
Equipment: {state.get('equipment_record')}
Telemetry: {state.get('telemetry_data')}
Compliance: {state.get('compliance_data')}
Historical logs: {state.get('historical_rag_data')}{rag_docs_text}{cemg_context_text}
Weather/voyage: {state.get('weather_voyage_data')}
Port/maps: {state.get('maps_data')}"""

    response, audit_rec = await call_llm_with_audit("SynthesisAgent", prompt)
    
    return {
        "final_synthesis": {"evaluation": response.content + atex_note, "sources_used": used_keys},
        "audit_records": audit_records + [audit_rec],
    }


async def output_guardrail_node(state: AgentState) -> Dict[str, Any]:
    if state.get("guardrail_violation"):
        return {"output_guardrail_applied": False}
        
    synthesis = state["final_synthesis"]["evaluation"]
    equipment = state.get("equipment_record")
    alert = state.get("atex_alert")
    
    applied = False
    new_synthesis = synthesis
    
    if equipment and equipment.get("is_atex_zone") and alert:
        severity = alert.get("severity")
        if severity in ("warning", "critical"):
            warning_words = ["SAFETY ALERT", "ATEX", "protocol", "gas reading", "explosive", "LEL"]
            has_warning = any(word.lower() in synthesis.lower() for word in warning_words)
            
            if not has_warning:
                safety_alert = f"\n\nSAFETY ALERT ({severity.upper()}): {equipment['name']} is in {equipment['atex_zone_class']} — gas reading {alert['reading']['gas_reading_pct_lel']}% LEL. Follow ATEX zone protocol before proceeding."
                new_synthesis = synthesis + safety_alert
                applied = True
                
    docs = state.get("rag_documents", [])
    for doc in docs:
        if "7.0 mm/s" in doc["content"] and "9.0 mm/s" in doc["content"]:
            if "10" in synthesis or "9." in synthesis:
                if "shutdown" not in synthesis.lower() and "critical" not in synthesis.lower():
                    new_synthesis += "\n\nCRITICAL SPEC LIMIT: Manual indicates vibrations exceeding 9.0 mm/s require immediate shutdown."
                    applied = True
                    
    return {
        "final_synthesis": {
            "evaluation": new_synthesis,
            "sources_used": state["final_synthesis"]["sources_used"]
        },
        "output_guardrail_applied": applied
    }


async def logbook_extraction_node(state: AgentState) -> Dict[str, Any]:
    class LogExtraction(BaseModel):
        log_type: Literal["maintenance", "diagnostic", "checklist", "incident"]
        symptom: Optional[str] = None
        action_taken: Optional[str] = None
        outcome: Optional[str] = None
        extraction_confidence: float

    prompt = f"""Extract a structured maintenance/diagnostic log entry from this crew note.
If a field isn't mentioned, leave it null. Rate your extraction_confidence 0-1.

Crew note: "{state['user_query']}\""""

    extraction, audit_rec = await call_llm_with_audit(
        "LogbookExtractionAgent",
        prompt,
        structured_schema=LogExtraction,
        confidence_score=0.9
    )

    equipment = state.get("equipment_record")
    equipment_id = equipment["id"] if equipment else "unresolved"
    structured_summary = {
        "symptom": extraction.symptom, "action_taken": extraction.action_taken, "outcome": extraction.outcome,
    }

    log_id = str(uuid.uuid4())
    if equipment:
        await db.insert_equipment_log(
            log_id=log_id, equipment_id=equipment_id, thread_id=state["thread_id"],
            engineer_id=state["engineer_id"], raw_entry=state["user_query"],
            structured_summary=structured_summary, log_type=extraction.log_type,
            confidence=extraction.extraction_confidence,
        )

    flag_for_review = extraction.extraction_confidence < 0.6 or not equipment
    result = {
        "log_id": log_id, "equipment_resolved": equipment is not None,
        "structured_summary": structured_summary, "flagged_for_review": flag_for_review,
    }
    
    audit_rec["gate_reasoning"] = "logbook_entry interaction_type — deterministic, not confidence-gated"
    audit_rec["tool_name"] = "logbook_extractor"
    audit_rec["input_payload"] = json.dumps({"equipment_id": equipment_id})
    audit_rec["output_payload"] = json.dumps(result)
    audit_rec["is_used_by_synthesis"] = 1
    
    audit_records = state.get("audit_records", []) + [audit_rec]
    return {"logbook_result": result, "audit_records": audit_records}


async def vessel_compatibility_node(state: AgentState) -> Dict[str, Any]:
    profile = await db.get_crew_profile(state["engineer_id"])
    vessel_equipment = await db.get_vessel_equipment(state["vessel_id"])

    known_models = set(json.loads(profile["known_equipment_models"])) if profile and profile.get("known_equipment_models") else set()
    known_classes = set(json.loads(profile["known_vessel_classes"])) if profile and profile.get("known_vessel_classes") else set()

    unfamiliar = [
        eq for eq in vessel_equipment
        if f"{eq.get('manufacturer')}/{eq.get('model')}" not in known_models
    ]
    class_is_new = state["vessel_class"] not in known_classes

    prompt = f"""A crew member is being onboarded onto a {state['vessel_class']}-class vessel.
Their known vessel classes: {sorted(known_classes) or 'none on file'}.
Equipment on this vessel they have NOT worked with before: {[eq['name'] for eq in unfamiliar]}.

Write a short, practical onboarding brief: what's different here vs. what they likely know,
and which unfamiliar equipment to review first, prioritizing critical-tier machinery."""

    response, audit_rec = await call_llm_with_audit("VesselCompatibilityAgent", prompt)
    
    result = {
        "vessel_class_is_new": class_is_new,
        "unfamiliar_equipment": [eq["id"] for eq in unfamiliar],
        "brief": response.content,
    }
    
    audit_rec["gate_reasoning"] = "onboarding_check interaction_type"
    audit_rec["tool_name"] = "crew_profile_lookup"
    audit_rec["input_payload"] = json.dumps({"engineer_id": state["engineer_id"]})
    audit_rec["output_payload"] = json.dumps(result)
    audit_rec["is_used_by_synthesis"] = 1
    
    audit_records = state.get("audit_records", []) + [audit_rec]
    return {"onboarding_result": result, "audit_records": audit_records}


async def checklist_agent_node(state: AgentState) -> Dict[str, Any]:
    equipment = state.get("equipment_record")
    templates = await db.get_checklist_for_vessel_class(
        state["vessel_class"], equipment["id"] if equipment else None
    )
    result = {"templates": templates}
    audit_records = state.get("audit_records", []) + [{
        "agent_name": "checklist_agent", "gate_fired": 1,
        "gate_reasoning": "checklist_request interaction_type", "confidence_score": state["triage_decision"]["confidence"],
        "tool_name": "checklist_lookup", "input_payload": json.dumps({"vessel_class": state["vessel_class"]}),
        "output_payload": json.dumps(result), "latency_ms": 0, "is_used_by_synthesis": 1,
        "prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0.0
    }]
    return {"checklist_result": result, "audit_records": audit_records}


async def action_agent(state: AgentState) -> Dict[str, Any]:
    decision = state["triage_decision"]
    warranted = decision["urgency"] in ("elevated", "urgent") and not state.get("guardrail_violation")
    if warranted:
        equipment = state.get("equipment_record")
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                """INSERT INTO work_orders
                   (id, tenant_id, vessel_id, thread_id, turn_id, equipment_id,
                    created_by_agent, justification, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (str(uuid.uuid4()), state["tenant_id"], state["vessel_id"], state["thread_id"],
                 state["turn_id"], equipment["id"] if equipment else "unresolved", "ActionAgent",
                 state["final_synthesis"]["evaluation"][:500]),
            )
            await conn.commit()
    return {"work_order_created": warranted}


async def profile_consolidation_node(state: AgentState) -> Dict[str, Any]:
    query = state["user_query"].lower()
    engineer_id = state["engineer_id"]
    tenant_id = state["tenant_id"]
    
    updated = False
    vessel_class = None
    equipment_model = None
    
    if any(keyword in query for keyword in ("certified on", "worked on", "experienced with", "knows how to")):
        if "framo" in query:
            equipment_model = "Framo/SD125"
            updated = True
        if "sulzer" in query:
            equipment_model = "Sulzer/AHLSTAR-APP"
            updated = True
        if "aframax" in query:
            vessel_class = "Aframax"
            updated = True
            
    if updated:
        await db.update_crew_profile(engineer_id, tenant_id, vessel_class=vessel_class, equipment_model=equipment_model)
        
    await db.insert_message(str(uuid.uuid4()), state["thread_id"], "user", state["user_query"])
    synthesis = state.get("final_synthesis", {}).get("evaluation")
    if synthesis:
        await db.insert_message(str(uuid.uuid4()), state["thread_id"], "assistant", synthesis)
        
    return {}


async def flush_audit_records(state: AgentState) -> None:
    records = state.get("audit_records", [])
    if not records:
        return
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executemany(
            """INSERT INTO tool_call_audit
               (id, tenant_id, thread_id, turn_id, agent_name, gate_fired,
                gate_reasoning, confidence_score, tool_name, input_payload,
                output_payload, is_used_by_synthesis, latency_ms,
                prompt_tokens, completion_tokens, estimated_cost)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (str(uuid.uuid4()), state["tenant_id"], state["thread_id"], state["turn_id"],
                 r["agent_name"], r["gate_fired"], r["gate_reasoning"], r["confidence_score"],
                 r["tool_name"], r["input_payload"], r["output_payload"],
                 r.get("is_used_by_synthesis", 0), r["latency_ms"],
                 r.get("prompt_tokens", 0), r.get("completion_tokens", 0), r.get("estimated_cost", 0.0))
                for r in records
            ],
        )
        await conn.commit()


async def audit_node(state: AgentState) -> Dict[str, Any]:
    await flush_audit_records(state)
    return {}


# --- 8. Graph assembly ---

workflow = StateGraph(AgentState)

# Add all nodes
workflow.add_node("InputGuardrail", input_guardrail_node)
workflow.add_node("TriageRouter", triage_router_node)
workflow.add_node("ResolveEquipment", resolve_equipment_node)
workflow.add_node("DocumentRetriever", document_retriever_node)
workflow.add_node("ATEXHazardCheck", atex_hazard_check_node)
workflow.add_node("FanOutOrchestrator", fan_out_orchestrator)
workflow.add_node("SynthesisAgent", synthesis_agent)
workflow.add_node("OutputGuardrail", output_guardrail_node)
workflow.add_node("ActionAgent", action_agent)
workflow.add_node("ProfileConsolidationAgent", profile_consolidation_node)
workflow.add_node("LogbookExtractionAgent", logbook_extraction_node)
workflow.add_node("VesselCompatibilityAgent", vessel_compatibility_node)
workflow.add_node("ChecklistAgent", checklist_agent_node)
workflow.add_node("AuditNode", audit_node)

# Connect edges
workflow.set_entry_point("InputGuardrail")
workflow.add_conditional_edges("InputGuardrail", route_input_guardrail, {
    "TriageRouter": "TriageRouter",
    "SynthesisAgent": "SynthesisAgent"
})

workflow.add_edge("TriageRouter", "ResolveEquipment")
workflow.add_edge("ResolveEquipment", "DocumentRetriever")
workflow.add_edge("DocumentRetriever", "ATEXHazardCheck")

workflow.add_conditional_edges("ATEXHazardCheck", route_by_interaction, {
    "LogbookExtractionAgent": "LogbookExtractionAgent",
    "VesselCompatibilityAgent": "VesselCompatibilityAgent",
    "ChecklistAgent": "ChecklistAgent",
    "FanOutOrchestrator": "FanOutOrchestrator",
})

workflow.add_edge("FanOutOrchestrator", "SynthesisAgent")
workflow.add_edge("SynthesisAgent", "OutputGuardrail")
workflow.add_edge("OutputGuardrail", "ActionAgent")
workflow.add_edge("ActionAgent", "ProfileConsolidationAgent")
workflow.add_edge("ProfileConsolidationAgent", "AuditNode")

workflow.add_edge("LogbookExtractionAgent", "AuditNode")
workflow.add_edge("VesselCompatibilityAgent", "AuditNode")
workflow.add_edge("ChecklistAgent", "AuditNode")

workflow.add_edge("AuditNode", END)


# Lazy Compiled Graph Proxy to handle AsyncSqliteSaver loops
class LazyCompiledGraph:
    def __init__(self, workflow_graph):
        self.workflow_graph = workflow_graph
        self._compiled_app = None
        self._conn = None
        self._saver = None

    async def _ensure_compiled(self):
        if self._compiled_app is None:
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            
            self._conn = aiosqlite.connect(CHECKPOINTS_DB_PATH)
            await self._conn.__aenter__()
            self._saver = AsyncSqliteSaver(self._conn)
            await self._saver.setup()
            
            self._compiled_app = self.workflow_graph.compile(
                checkpointer=self._saver,
                interrupt_before=["ActionAgent"]
            )

    async def ainvoke(self, *args, **kwargs):
        await self._ensure_compiled()
        return await self._compiled_app.ainvoke(*args, **kwargs)

    async def astream(self, *args, **kwargs):
        await self._ensure_compiled()
        async for item in self._compiled_app.astream(*args, **kwargs):
            yield item

    async def aget_state(self, *args, **kwargs):
        await self._ensure_compiled()
        return await self._compiled_app.aget_state(*args, **kwargs)

    async def aupdate_state(self, *args, **kwargs):
        await self._ensure_compiled()
        return await self._compiled_app.aupdate_state(*args, **kwargs)


# Export compiled proxy app
app = LazyCompiledGraph(workflow)
