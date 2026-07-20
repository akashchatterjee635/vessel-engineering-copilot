import asyncio
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
DB_PATH = "test_vessel_copilot.db"

TENANT_ID = "tenant-001"
VESSEL_ID = "vessel-001"
ENGINEER_ID = "engineer-001"
THREAD_ID = "thread-001"

PUMP_EQUIPMENT_ID = "equip-aux-pump-001"      # ordinary, non-ATEX
CARGO_PUMP_EQUIPMENT_ID = "equip-cargo-pump-001"  # ATEX Zone 1


def seed():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except Exception:
            pass
    if os.path.exists("test_vessel_checkpoints.db"):
        try:
            os.remove("test_vessel_checkpoints.db")
        except Exception:
            pass
    if os.path.exists("cemg_memory.db"):
        try:
            os.remove("cemg_memory.db")
        except Exception:
            pass

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(open(SCHEMA_PATH).read())

    conn.execute("INSERT INTO tenants (id, name, fleet_operator) VALUES (?, ?, ?)",
                 (TENANT_ID, "Test Fleet Ops", "Test Shipping Co"))

    conn.execute("""INSERT INTO vessels (id, tenant_id, name, imo_number, vessel_type, vessel_class, build_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                 (VESSEL_ID, TENANT_ID, "MT Test Voyager", 9999999, "oil_tanker", "Aframax", "2019-05-01"))

    conn.execute("""INSERT INTO threads (id, tenant_id, vessel_id, engineer_id, title)
                    VALUES (?, ?, ?, ?, ?)""",
                 (THREAD_ID, TENANT_ID, VESSEL_ID, ENGINEER_ID, "Test thread"))

    # Ordinary equipment — no ATEX
    conn.execute("""INSERT INTO equipment
                    (id, vessel_id, name, system_category, criticality_tier, is_atex_zone,
                     atex_zone_class, manufacturer, model, manual_doc_ref)
                    VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)""",
                 (PUMP_EQUIPMENT_ID, VESSEL_ID, "Aux Boiler Feed Pump #2", "propulsion", "sub_critical",
                  "Sulzer", "AHLSTAR-APP", "doc://manuals/sulzer-ahlstar-app"))

    # ATEX Zone 1 equipment — cargo pump on a tanker
    conn.execute("""INSERT INTO equipment
                    (id, vessel_id, name, system_category, criticality_tier, is_atex_zone,
                     atex_zone_class, manufacturer, model, manual_doc_ref)
                    VALUES (?, ?, ?, ?, ?, 1, 'Zone 1', ?, ?, ?)""",
                 (CARGO_PUMP_EQUIPMENT_ID, VESSEL_ID, "Cargo Pump #1", "cargo", "critical",
                  "Framo", "SD125", "doc://manuals/framo-sd125"))

    # Crew profile — engineer has worked Suezmax, VLCC; does NOT know Aframax or Framo cargo pumps
    conn.execute("""INSERT INTO crew_profiles (id, engineer_id, tenant_id, known_vessel_classes, known_equipment_models)
                    VALUES (?, ?, ?, ?, ?)""",
                 ("crew-profile-001", ENGINEER_ID, TENANT_ID,
                  json.dumps(["Suezmax", "VLCC"]),
                  json.dumps(["Sulzer/AHLSTAR-APP"])))  # knows the aux pump model, not the cargo pump

    # Checklist template for this vessel class
    conn.execute("""INSERT INTO checklist_templates (id, equipment_id, vessel_class, title, items_json)
                    VALUES (?, NULL, ?, ?, ?)""",
                 ("checklist-001", "Aframax", "Daily Engine Room Rounds",
                  json.dumps(["Check bilge levels", "Inspect aux pump seals", "Log ambient engine room temp"])))

    # Documents for RAG search
    conn.execute("""INSERT INTO documents (id, equipment_id, vessel_class, title, content, section_name)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                 ("doc-aux-pump-001", PUMP_EQUIPMENT_ID, "Aframax", "Sulzer AHLSTAR Troubleshooting Guide",
                  "If grinding noise is observed on startup: 1. Verify gland packing tightness. If too tight, loosen slightly and monitor temperature. 2. Check alignment of pump shaft. Misalignment causes coupling wear and grinding noise. 3. Check lubrication level in bearing housing. Low oil will cause bearing failure.",
                  "Troubleshooting"))

    conn.execute("""INSERT INTO documents (id, equipment_id, vessel_class, title, content, section_name)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                 ("doc-cargo-pump-001", CARGO_PUMP_EQUIPMENT_ID, "Aframax", "Framo SD125 Cargo Pump Safety Procedures",
                  "Framo SD125 is Zone 1 ATEX rated equipment. Crucial operation limits: 1. Max vibration amplitude: 7.0 mm/s. Vibrations exceeding 9.0 mm/s require immediate shutdown. 2. LEL Gas concentration: Keep below 10% LEL. At 20% LEL, automatic shutdown must be initiated and area ventilated.",
                  "ATEX Safety"))

    conn.execute("""INSERT INTO documents (id, equipment_id, vessel_class, title, content, section_name)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                 ("doc-aframax-001", None, "Aframax", "Aframax Class Tanker Safety Guide",
                  "ATEX Zoned Equipment Guidelines: All equipment located in cargo zones (decks, pump rooms) must conform to ATEX Zone 1 or Zone 0 requirements. Any gas readings exceeding 10% LEL must be treated as alert, and 20% LEL as critical emergency. Hot work is strictly prohibited in these zones without formal gas-free certification.",
                  "Zoned Safety Guidelines"))

    conn.commit()
    conn.close()
    print(f"Seeded {DB_PATH}")
    print(f"  tenant={TENANT_ID} vessel={VESSEL_ID} engineer={ENGINEER_ID} thread={THREAD_ID}")
    print(f"  equipment: {PUMP_EQUIPMENT_ID} (non-ATEX), {CARGO_PUMP_EQUIPMENT_ID} (ATEX Zone 1)")


if __name__ == "__main__":
    seed()
