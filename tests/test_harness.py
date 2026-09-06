import asyncio
import os
import sqlite3
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["VESSEL_COPILOT_DB"] = "test_vessel_copilot.db"
os.environ["VESSEL_COPILOT_CHECKPOINTS_DB"] = "test_vessel_checkpoints.db"
os.environ["OPENAI_API_KEY"] = "sk-dummy-for-import-only"

from seed import (
    ENGINEER_ID,
    TENANT_ID,
    THREAD_ID,
    VESSEL_ID,
)

import graph as g


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeRunnable:
    """Returns whatever fixed value is handed to it, async, no real API call."""

    def __init__(self, value):
        self.value = value

    async def ainvoke(self, *args, **kwargs):
        return self.value


def make_fake_llm(
    default_text="Mock synthesis: assessment generated from available context.",
):
    """Patches module-level _llm / _triage_llm with fakes.
    with_structured_output is patched to inspect the target schema class name
    so the same fake object can serve both TriageDecision and LogExtraction calls."""

    class FakeLLM:
        def __init__(self):
            self.text_response = default_text

        async def ainvoke(self, *a, **kw):
            return FakeMessage(self.text_response)

        def with_structured_output(self, schema):
            name = schema.__name__
            if name == "TriageDecision":
                return FakeRunnable(CURRENT_TRIAGE_DECISION[0])
            elif name == "LogExtraction":
                return FakeRunnable(CURRENT_LOG_EXTRACTION[0])
            elif name == "GroundingCheck":
                return FakeRunnable(
                    g.GroundingCheck(is_supported=True, unsupported_claims=[], source_map={}, revised_evaluation=None)
                )
            elif name == "ProfileExtraction":
                return FakeRunnable(
                    g.ProfileExtraction(
                        equipment=None, vessel_class=None, claim_type="unknown", polarity="neutral", confidence=1.0
                    )
                )
            raise ValueError(f"Unmocked schema: {name}")

    return FakeLLM()


# Mutable single-slot "queues" so nested with_structured_output() calls made
# fresh inside logbook_extraction_node still resolve to the right fixture per test.
CURRENT_TRIAGE_DECISION = [None]
CURRENT_LOG_EXTRACTION = [None]


async def run_scenario(name, user_query, triage_decision, log_extraction=None, engineer_id=ENGINEER_ID):
    print(f"\n{'=' * 70}\nSCENARIO: {name}\n{'=' * 70}")
    CURRENT_TRIAGE_DECISION[0] = triage_decision
    CURRENT_LOG_EXTRACTION[0] = log_extraction

    fake = make_fake_llm()
    g._llm = fake
    g._triage_llm = FakeRunnable(triage_decision)

    turn_id = str(uuid.uuid4())
    state = {
        "tenant_id": TENANT_ID,
        "vessel_id": VESSEL_ID,
        "vessel_class": "Aframax",
        "thread_id": THREAD_ID,
        "engineer_id": engineer_id,
        "user_query": user_query,
        "turn_id": turn_id,
    }

    cfg = {"configurable": {"thread_id": turn_id}}
    try:
        result = await g.app.ainvoke(state, config=cfg)

        # Check if we hit the ActionAgent interrupt (which we do for elevated urgency)
        graph_state = await g.app.aget_state(cfg)
        if graph_state.next and "ActionAgent" in graph_state.next:
            print("(paused before ActionAgent -- simulating human approval, resuming)")
            # Simulate human clicking 'Approve' in UI
            await g.app.aupdate_state(
                cfg, {"triage_decision": {**graph_state.values["triage_decision"], "human_approval": "approved"}}
            )
            result = await g.app.ainvoke(None, config=cfg)

        print(
            "Graph completed. Interaction type:",
            result["triage_decision"]["interaction_type"],
        )
        if result.get("atex_alert"):
            print("ATEX alert:", result["atex_alert"])
        if result.get("logbook_result"):
            print("Logbook result:", result["logbook_result"])
        if result.get("onboarding_result"):
            print("Onboarding brief:", result["onboarding_result"]["brief"][:200])
            print(
                "Unfamiliar equipment:",
                result["onboarding_result"]["unfamiliar_equipment"],
            )
        if result.get("checklist_result"):
            print(
                "Checklist templates found:",
                len(result["checklist_result"]["templates"]),
            )
        if result.get("final_synthesis"):
            print("Synthesis:", result["final_synthesis"]["evaluation"][:200])
        print("Audit records generated:", len(result.get("audit_records", [])))
        return result
    except Exception as e:
        print(f"*** FAILED: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return None


async def main():
    # 1. Diagnostic path, non-ATEX equipment, normal telemetry+historical gating
    await run_scenario(
        "Diagnostic query on ordinary equipment",
        "The aux boiler feed pump is making a grinding noise on startup",
        g.TriageDecision(
            interaction_type="diagnostic",
            urgency="elevated",
            equipment_hint="aux boiler feed pump",
            needs_telemetry=True,
            needs_compliance_lookup=False,
            needs_historical_rag=True,
            needs_weather_voyage=False,
            needs_maps=False,
            confidence=0.9,
            reasoning="Symptom described on named equipment, telemetry and history relevant.",
        ),
    )

    # 2. Logbook entry, non-ATEX
    await run_scenario(
        "Logbook entry",
        "Tightened the gland packing on the aux boiler feed pump, noise reduced, no further action needed.",
        g.TriageDecision(
            interaction_type="logbook_entry",
            urgency="routine",
            equipment_hint="aux boiler feed pump",
            needs_telemetry=False,
            needs_compliance_lookup=False,
            needs_historical_rag=False,
            needs_weather_voyage=False,
            needs_maps=False,
            confidence=0.95,
            reasoning="Crew reporting completed maintenance action.",
        ),
        log_extraction=SimpleNamespace(
            log_type="maintenance",
            symptom="grinding noise on startup",
            action_taken="tightened gland packing",
            outcome="noise reduced, no further action needed",
            extraction_confidence=0.92,
        ),
    )

    # 3. Onboarding compatibility check
    await run_scenario(
        "Onboarding compatibility check",
        "I just got assigned to this vessel, what's different from what I'm used to?",
        g.TriageDecision(
            interaction_type="onboarding_check",
            urgency="routine",
            equipment_hint=None,
            needs_telemetry=False,
            needs_compliance_lookup=False,
            needs_historical_rag=False,
            needs_weather_voyage=False,
            needs_maps=False,
            confidence=0.9,
            reasoning="Crew requesting onboarding brief.",
        ),
    )

    # 4. Checklist request
    await run_scenario(
        "Checklist request",
        "Can I get today's engine room rounds checklist?",
        g.TriageDecision(
            interaction_type="checklist_request",
            urgency="routine",
            equipment_hint=None,
            needs_telemetry=False,
            needs_compliance_lookup=False,
            needs_historical_rag=False,
            needs_weather_voyage=False,
            needs_maps=False,
            confidence=0.9,
            reasoning="Crew requesting standard checklist.",
        ),
    )

    # 5. ATEX hazard scenario — diagnostic on the Zone 1 cargo pump
    await run_scenario(
        "ATEX Zone 1 equipment diagnostic (hazard check should fire)",
        "Cargo pump #1 seems to be running hotter than usual",
        g.TriageDecision(
            interaction_type="diagnostic",
            urgency="elevated",
            equipment_hint="Cargo Pump #1",
            needs_telemetry=False,
            needs_compliance_lookup=False,
            needs_historical_rag=False,
            needs_weather_voyage=False,
            needs_maps=False,
            confidence=0.85,
            reasoning="Symptom on ATEX equipment; triage itself did not request telemetry.",
        ),
    )

    # 6. Port assistance
    await run_scenario(
        "Port assistance after docking",
        "We just docked, what's the weather and are there spare parts services nearby?",
        g.TriageDecision(
            interaction_type="port_assistance",
            urgency="routine",
            equipment_hint=None,
            needs_telemetry=False,
            needs_compliance_lookup=False,
            needs_historical_rag=False,
            needs_weather_voyage=True,
            needs_maps=True,
            confidence=0.9,
            reasoning="Post-docking logistics query.",
        ),
    )

    # 7. ATEX critical threshold — force a high gas reading to exercise the
    # atex_hazard_events insert path, which scenario 5's default mock never hit.
    original_run_telemetry = g.run_telemetry

    async def hot_telemetry(tenant_id, vessel_id, equipment_id):
        return {
            "equipment_id": equipment_id,
            "vibration_amplitude": 9.1,
            "frequency_band": "high",
            "gas_reading_pct_lel": 25.0,
        }

    g.run_telemetry = hot_telemetry
    try:
        await run_scenario(
            "ATEX critical gas reading (should write atex_hazard_events row)",
            "Cargo pump #1 area feels off, can you check it",
            g.TriageDecision(
                interaction_type="diagnostic",
                urgency="urgent",
                equipment_hint="Cargo Pump #1",
                needs_telemetry=False,
                needs_compliance_lookup=False,
                needs_historical_rag=False,
                needs_weather_voyage=False,
                needs_maps=False,
                confidence=0.8,
                reasoning="Vague symptom on ATEX equipment.",
            ),
        )
    finally:
        g.run_telemetry = original_run_telemetry

    print(f"\n{'=' * 70}\nDB STATE AFTER ALL SCENARIOS\n{'=' * 70}")
    conn = sqlite3.connect("test_vessel_copilot.db")
    for table in [
        "equipment_logs",
        "atex_hazard_events",
        "work_orders",
        "tool_call_audit",
    ]:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"{table}: {cur.fetchone()[0]} rows")

    conn.close()
    await g.app.aclose()


if __name__ == "__main__":
    asyncio.run(main())
