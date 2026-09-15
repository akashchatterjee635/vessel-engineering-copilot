import re

with open("graph.py", "r", encoding="utf-8") as f:
    content = f.read()

resilience_code = """
# --- DISTRIBUTED SYSTEMS RESILIENCE ---
class CircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"

    def record_success(self):
        self.failures = 0
        self.state = "CLOSED"

    def can_execute(self):
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        if self.state == "HALF_OPEN":
            return True

circuit_breakers = {}

def get_circuit_breaker(tool_name):
    if tool_name not in circuit_breakers:
        circuit_breakers[tool_name] = CircuitBreaker()
    return circuit_breakers[tool_name]
# ----------------------------------------
"""

if "# --- DISTRIBUTED SYSTEMS RESILIENCE ---" not in content:
    # insert after imports
    match = re.search(r"import db\n", content)
    if match:
        content = content[: match.end()] + resilience_code + content[match.end() :]

# Now rewrite execute_tool_with_cemg
target_func = """async def execute_tool_with_cemg(tool_name: str, coro_factory, params: dict, state: AgentState) -> dict[str, Any]:
    engineer_id = state["engineer_id"]
    tenant_id = state["tenant_id"]
    turn_id = state["turn_id"]"""

replacement_func = """async def execute_tool_with_cemg(tool_name: str, coro_factory, params: dict, state: AgentState) -> dict[str, Any]:
    engineer_id = state["engineer_id"]
    tenant_id = state["tenant_id"]
    turn_id = state["turn_id"]

    # DISTRIBUTED RESILIENCE: Circuit Breaker
    cb = get_circuit_breaker(tool_name)
    if not cb.can_execute():
        state["cemg_memory_context"] = state.get("cemg_memory_context", "") + f"Skipped tool {tool_name} due to OPEN Circuit Breaker.\\n"
        return {"error": "CIRCUIT_BREAKER_OPEN", "message": f"Circuit breaker open for {tool_name}. Fallback triggered."}
"""
if target_func in content:
    content = content.replace(target_func, replacement_func)

target_exec = """    start = time.perf_counter()
    try:
        # Simulate connection/execution failures for testing
        if tool_name == "telemetry_mcp" and params.get("equipment_id") == "equip-failed-telemetry":
            raise ConnectionError("Telemetry connection timed out (sensor offline).")

        res = await coro_factory()
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Store success experience in CEMG"""

replacement_exec = """    start = time.perf_counter()
    try:
        # DISTRIBUTED RESILIENCE: Retry with exponential backoff & Timeout
        res = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Simulate connection/execution failures for testing
                if tool_name == "telemetry_mcp" and params.get("equipment_id") == "equip-failed-telemetry":
                    raise ConnectionError("Telemetry connection timed out (sensor offline).")
                
                # Enforce timeout (e.g. 5 seconds)
                res = await asyncio.wait_for(coro_factory(), timeout=5.0)
                break
            except (ConnectionError, asyncio.TimeoutError) as e:
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(2 ** attempt) # Exponential backoff

        latency_ms = int((time.perf_counter() - start) * 1000)

        # DISTRIBUTED RESILIENCE: Record Success
        cb.record_success()

        # Store success experience in CEMG"""

if target_exec in content:
    content = content.replace(target_exec, replacement_exec)

target_catch = """    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Store failure experience in CEMG"""

replacement_catch = """    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)

        # DISTRIBUTED RESILIENCE: Record Failure
        cb.record_failure()

        # Store failure experience in CEMG"""

if target_catch in content:
    content = content.replace(target_catch, replacement_catch)

with open("graph.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
