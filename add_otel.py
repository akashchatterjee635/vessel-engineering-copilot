import re

with open("graph.py", "r", encoding="utf-8") as f:
    content = f.read()

otel_code = """
# --- OPENTELEMETRY TRACING ---
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)
# Export to console for now, in a real system this would go to Jaeger/OTLP
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
# ------------------------------
"""

if "# --- OPENTELEMETRY TRACING ---" not in content:
    match = re.search(r"# --- PROMETHEUS METRICS ---", content)
    if match:
        content = content[: match.start()] + otel_code + content[match.start() :]


# Instrument execute_tool_with_cemg
target_tool = """async def execute_tool_with_cemg(tool_name: str, coro_factory, params: dict, state: AgentState) -> dict[str, Any]:
    engineer_id = state["engineer_id"]"""
replace_tool = """async def execute_tool_with_cemg(tool_name: str, coro_factory, params: dict, state: AgentState) -> dict[str, Any]:
    with tracer.start_as_current_span(f"mcp_call:{tool_name}") as span:
        span.set_attribute("tool_name", tool_name)
        span.set_attribute("params", str(params))
        return await _execute_tool_with_cemg_inner(tool_name, coro_factory, params, state, span)

async def _execute_tool_with_cemg_inner(tool_name: str, coro_factory, params: dict, state: AgentState, span) -> dict[str, Any]:
    engineer_id = state["engineer_id"]"""
content = content.replace(target_tool, replace_tool)

target_tool_success = """        cb.record_success()
        update_cb_metrics(tool_name, cb.state)"""
replace_tool_success = """        cb.record_success()
        update_cb_metrics(tool_name, cb.state)
        span.set_attribute("success", True)"""
content = content.replace(target_tool_success, replace_tool_success)

# Instrument call_llm_with_audit
target_llm = """async def call_llm_with_audit(
    node_name: str,
    prompt: str,
    system_prompt: str | None = None,
    structured_schema: Any | None = None,
    confidence_score: float = 1.0,
) -> tuple[Any, dict]:
    start = time.perf_counter()"""
replace_llm = """async def call_llm_with_audit(
    node_name: str,
    prompt: str,
    system_prompt: str | None = None,
    structured_schema: Any | None = None,
    confidence_score: float = 1.0,
) -> tuple[Any, dict]:
    with tracer.start_as_current_span(f"llm_call:{node_name}") as span:
        return await _call_llm_with_audit_inner(node_name, prompt, system_prompt, structured_schema, confidence_score, span)

async def _call_llm_with_audit_inner(
    node_name: str,
    prompt: str,
    system_prompt: str | None,
    structured_schema: Any | None,
    confidence_score: float,
    span
) -> tuple[Any, dict]:
    start = time.perf_counter()"""
content = content.replace(target_llm, replace_llm)

with open("graph.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
