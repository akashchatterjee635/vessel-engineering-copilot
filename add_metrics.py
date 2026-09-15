import re

with open("graph.py", "r", encoding="utf-8") as f:
    content = f.read()

metrics_code = """
# --- PROMETHEUS METRICS ---
from prometheus_client import Counter, Histogram, Gauge

WORKFLOW_LATENCY = Histogram('workflow_latency_seconds', 'Latency of workflow', ['interaction_type'])
TOOL_LATENCY = Histogram('mcp_tool_latency_seconds', 'Latency of MCP calls', ['tool_name'])
TOOL_FAILURES = Counter('mcp_tool_failures_total', 'Failures of MCP calls', ['tool_name'])
TOKEN_USAGE = Counter('llm_token_usage_total', 'Tokens used', ['agent_name', 'token_type'])
COST_ESTIMATE = Counter('llm_cost_estimate_usd', 'Estimated LLM cost in USD', ['agent_name'])
GUARDRAIL_BLOCKS = Counter('guardrail_blocks_total', 'Number of times output was blocked by guardrail', ['agent_name'])
CIRCUIT_BREAKER_STATE = Gauge('circuit_breaker_state', 'State of circuit breaker (0=CLOSED, 1=HALF_OPEN, 2=OPEN)', ['tool_name'])

def update_cb_metrics(tool_name, state_str):
    mapping = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}
    CIRCUIT_BREAKER_STATE.labels(tool_name=tool_name).set(mapping.get(state_str, 0))
# --------------------------
"""

if "# --- PROMETHEUS METRICS ---" not in content:
    match = re.search(r"# --- DISTRIBUTED SYSTEMS RESILIENCE ---", content)
    if match:
        content = content[: match.start()] + metrics_code + content[match.start() :]

# Instrument CB
cb_success_target = """        # DISTRIBUTED RESILIENCE: Record Success
        cb.record_success()"""
cb_success_replacement = """        # DISTRIBUTED RESILIENCE: Record Success
        cb.record_success()
        update_cb_metrics(tool_name, cb.state)"""
content = content.replace(cb_success_target, cb_success_replacement)

cb_failure_target = """        # DISTRIBUTED RESILIENCE: Record Failure
        cb.record_failure()"""
cb_failure_replacement = """        # DISTRIBUTED RESILIENCE: Record Failure
        cb.record_failure()
        update_cb_metrics(tool_name, cb.state)
        TOOL_FAILURES.labels(tool_name=tool_name).inc()"""
content = content.replace(cb_failure_target, cb_failure_replacement)

# Instrument Latency
latency_target = """        latency_ms = int((time.perf_counter() - start) * 1000)

        # DISTRIBUTED RESILIENCE: Record Success"""
latency_replacement = """        latency_ms = int((time.perf_counter() - start) * 1000)
        TOOL_LATENCY.labels(tool_name=tool_name).observe(time.perf_counter() - start)

        # DISTRIBUTED RESILIENCE: Record Success"""
content = content.replace(latency_target, latency_replacement)

# Instrument LLM
llm_target = """    cost = (prompt_tokens * cost_prompt + completion_tokens * cost_completion) / 1_000_000.0

    audit_rec = {"""
llm_replacement = """    cost = (prompt_tokens * cost_prompt + completion_tokens * cost_completion) / 1_000_000.0

    TOKEN_USAGE.labels(agent_name=node_name, token_type="prompt").inc(prompt_tokens)
    TOKEN_USAGE.labels(agent_name=node_name, token_type="completion").inc(completion_tokens)
    COST_ESTIMATE.labels(agent_name=node_name).inc(cost)

    audit_rec = {"""
content = content.replace(llm_target, llm_replacement)

# Instrument Guardrail
guardrail_target = """        return {
            "final_synthesis": {
                "evaluation": f"GUARDRAIL BLOCKED: {state['guardrail_violation']}",
                "sources_used": [],
            }
        }"""
guardrail_replacement = """        GUARDRAIL_BLOCKS.labels(agent_name="SynthesisAgent").inc()
        return {
            "final_synthesis": {
                "evaluation": f"GUARDRAIL BLOCKED: {state['guardrail_violation']}",
                "sources_used": [],
            }
        }"""
content = content.replace(guardrail_target, guardrail_replacement)

with open("graph.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
