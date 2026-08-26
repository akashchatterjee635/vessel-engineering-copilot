"""
Real-LLM smoke test — uses the actual OpenAI API with gpt-5.4-mini.

Runs only 2 scenarios to minimise token spend:
  1. A simple informational query (triage + synthesis, no fan-out)
  2. A logbook entry extraction (structured output, minimal tokens)

Usage:
    python tests/real_llm_test.py
"""

import asyncio
import os
import sys
import uuid


# Load .env before importing graph (which inits ChatOpenAI at import time)
def load_dotenv(path=".env"):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


# Make sure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Verify API key is set
api_key = os.environ.get("OPENAI_API_KEY", "")
if not api_key or api_key.startswith("sk-..."):
    print("ERROR: OPENAI_API_KEY not set or is placeholder. Check your .env file.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Set test DB path and model
os.environ["VESSEL_COPILOT_DB"] = os.path.join(ROOT, "test_vessel_copilot.db")
os.environ["VESSEL_COPILOT_CHECKPOINTS_DB"] = os.path.join(ROOT, "test_vessel_checkpoints_real.db")
os.environ["MODEL_CONFIG_PATH"] = os.path.join(ROOT, "mlops", "model_config.yaml")
model = os.environ.get("VESSEL_COPILOT_MODEL", "gpt-5.4-mini")

print(f"Using model: {model}")
print(f"API key: {api_key[:8]}...{api_key[-4:]}")
print()

import graph as g

COMMON_STATE = {
    "tenant_id": "tenant-001",
    "vessel_id": "vessel-001",
    "vessel_class": "Aframax",
    "engineer_id": "engineer-001",
}


async def run_scenario(name: str, query: str, resume: bool = False):
    print(f"{'=' * 60}")
    print(f"REAL LLM TEST: {name}")
    print(f"Query: {query[:80]}")
    print(f"{'=' * 60}")

    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}}
    state = {**COMMON_STATE, "thread_id": thread_id, "user_query": query}

    result = await g.app.ainvoke(state, config=cfg)

    # If paused for HITL (ActionAgent), resume immediately
    if result is None or not result.get("final_synthesis"):
        print("(HITL pause detected — resuming...)")
        result = await g.app.ainvoke(None, config=cfg)

    synthesis = result.get("final_synthesis", {})
    triage = result.get("triage_decision", {})
    audit_count = len(result.get("audit_records", []))

    print(f"Interaction type : {triage.get('interaction_type', 'N/A')}")
    print(f"Urgency          : {triage.get('urgency', 'N/A')}")
    print(f"Reasoning        : {triage.get('reasoning', 'N/A')[:120]}")
    print()
    print("--- Synthesis ---")
    print(synthesis.get("evaluation", "No synthesis")[:500])
    print()
    print(f"Audit records    : {audit_count}")
    print()
    return result


async def main():
    # Seed the DB first
    print("Seeding test database...")
    import subprocess

    seed_script = os.path.join(ROOT, "tests", "seed.py")
    subprocess.run([sys.executable, seed_script], cwd=ROOT, check=True)
    print()

    # Scenario 1: Simple informational (cheapest — short prompt, short answer)
    await run_scenario(
        "Informational query (low token cost)",
        "What does ATEX Zone 1 classification mean for rotating equipment maintenance?",
    )

    # Scenario 2: Logbook entry extraction (structured output, 1 LLM call)
    await run_scenario(
        "Logbook entry extraction",
        "Completed gland packing replacement on aux boiler feed pump. Leak reduced from 30 drops/min to 5 drops/min. No abnormal noise observed post-restart.",
    )

    # Print final audit report
    print("=" * 60)
    print("AUDIT REPORT")
    print("=" * 60)
    import sqlite3

    db_path = os.path.join(ROOT, "test_vessel_copilot.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT agent_name, tool_name, prompt_tokens, completion_tokens, estimated_cost FROM tool_call_audit ORDER BY rowid DESC LIMIT 20"
    ).fetchall()
    total_cost = conn.execute("SELECT SUM(estimated_cost) FROM tool_call_audit").fetchone()[0] or 0
    total_tokens = (
        conn.execute("SELECT SUM(prompt_tokens)+SUM(completion_tokens) FROM tool_call_audit").fetchone()[0] or 0
    )
    conn.close()

    print(f"{'Agent':<30} {'Tool':<20} {'P.Tok':>6} {'C.Tok':>6} {'Cost':>8}")
    print("-" * 76)
    for agent, tool, p, c, cost in rows:
        if tool == "openai_llm":
            print(f"{(agent or ''):<30} {(tool or ''):<20} {(p or 0):>6} {(c or 0):>6} ${(cost or 0):>7.5f}")
    print("-" * 76)
    print(f"{'TOTAL':<52} {total_tokens:>6} tokens   ${total_cost:.5f}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
