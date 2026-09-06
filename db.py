"""Thin async data-access layer. Kept separate from graph.py so the
orchestration logic isn't tangled with SQL, and so these functions are
independently testable/mockable."""

import json
import os
from typing import Any

import aiosqlite

DB_PATH = os.environ.get("VESSEL_COPILOT_DB", "vessel_copilot.db")


async def resolve_equipment(vessel_id: str, name_hint: str | None) -> dict[str, Any] | None:
    """Fuzzy-match a crew-language equipment mention to a row in `equipment`.
    Production version: replace the LIKE match with an embedding search over
    equipment.name + known aliases — crew phrasing rarely matches nameplate text."""
    if not name_hint:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM equipment
               WHERE vessel_id = ? AND name LIKE ?
               LIMIT 1""",
            (vessel_id, f"%{name_hint}%"),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_crew_profile(engineer_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM crew_profiles WHERE engineer_id = ? ORDER BY updated_at DESC LIMIT 1",
            (engineer_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_vessel_equipment(vessel_id: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM equipment WHERE vessel_id = ?", (vessel_id,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_equipment_log_history(equipment_id: str, limit: int = 10) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM equipment_logs WHERE equipment_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (equipment_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_checklist_for_vessel_class(vessel_class: str, equipment_id: str | None) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if equipment_id:
            cursor = await db.execute(
                "SELECT * FROM checklist_templates WHERE equipment_id = ? OR vessel_class = ?",
                (equipment_id, vessel_class),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM checklist_templates WHERE vessel_class = ? AND equipment_id IS NULL",
                (vessel_class,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def insert_equipment_log(
    log_id: str,
    equipment_id: str,
    thread_id: str,
    engineer_id: str,
    raw_entry: str,
    structured_summary: dict[str, Any],
    log_type: str,
    confidence: float,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO equipment_logs
               (id, equipment_id, thread_id, engineer_id, raw_entry,
                structured_summary, log_type, extraction_confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log_id,
                equipment_id,
                thread_id,
                engineer_id,
                raw_entry,
                json.dumps(structured_summary),
                log_type,
                confidence,
            ),
        )
        await db.commit()


async def insert_atex_event(
    event_id: str,
    tenant_id: str,
    vessel_id: str,
    equipment_id: str,
    thread_id: str,
    zone_class: str,
    trigger_reading: dict[str, Any],
    severity: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO atex_hazard_events
               (id, tenant_id, vessel_id, equipment_id, thread_id, zone_class,
                trigger_reading, severity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                tenant_id,
                vessel_id,
                equipment_id,
                thread_id,
                zone_class,
                json.dumps(trigger_reading),
                severity,
            ),
        )
        await db.commit()


async def search_documents(vessel_class: str, equipment_id: str | None, query: str) -> list[dict[str, Any]]:
    """
    Hybrid RAG Search:
    1. Metadata filtering (vessel_class, equipment_id)
    2. Dense Semantic Search (Cosine Similarity using OpenAI embeddings)
    3. Lexical Search (Keyword overlap / TF-IDF approximation)
    4. Reciprocal Rank Fusion / Score Normalization
    """
    # Lexical setup
    words = [w.lower() for w in query.split() if len(w) > 3]

    # Semantic setup (if API key available, else skip semantic)
    query_embedding = None
    if os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_API_KEY") != "sk-dummy-for-import-only":
        try:
            from langchain_openai import OpenAIEmbeddings

            embedder = OpenAIEmbeddings(model="text-embedding-3-small")
            query_embedding = embedder.embed_query(query)
        except Exception:
            pass

    def cosine_similarity(v1, v2):
        if not v1 or not v2:
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # 1. Metadata filter
        if equipment_id:
            cursor = await db.execute(
                "SELECT * FROM documents WHERE vessel_class = ? OR equipment_id = ?",
                (vessel_class, equipment_id),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM documents WHERE vessel_class = ? OR equipment_id IS NULL",
                (vessel_class,),
            )
        rows = await cursor.fetchall()
        candidates = [dict(r) for r in rows]

        scored = []
        for cand in candidates:
            # 2. Lexical score
            lexical_score = 0.0
            text = (cand["title"] + " " + cand["content"]).lower()
            for w in words:
                if w in text:
                    lexical_score += 1.0

            # Normalize lexical (approx)
            if words:
                lexical_score = lexical_score / len(words)

            # 3. Semantic score
            semantic_score = 0.0
            if query_embedding and cand.get("embedding"):
                try:
                    doc_embedding = json.loads(cand["embedding"])
                    semantic_score = cosine_similarity(query_embedding, doc_embedding)
                except Exception:
                    pass

            # 4. Hybrid score (Weighted combination)
            hybrid_score = (lexical_score * 0.4) + (semantic_score * 0.6)
            scored.append((hybrid_score, cand))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for score, item in scored if score > 0] or candidates[:2]


async def update_crew_profile(
    engineer_id: str,
    tenant_id: str,
    vessel_class: str | None = None,
    equipment_model: str | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM crew_profiles WHERE engineer_id = ?", (engineer_id,))
        row = await cursor.fetchone()
        if row:
            profile = dict(row)
            known_classes = json.loads(profile["known_vessel_classes"])
            known_models = json.loads(profile["known_equipment_models"] or "[]")

            updated = False
            if vessel_class and vessel_class not in known_classes:
                known_classes.append(vessel_class)
                updated = True
            if equipment_model and equipment_model not in known_models:
                known_models.append(equipment_model)
                updated = True

            if updated:
                await db.execute(
                    "UPDATE crew_profiles SET known_vessel_classes = ?, known_equipment_models = ?, updated_at = CURRENT_TIMESTAMP WHERE engineer_id = ?",
                    (json.dumps(known_classes), json.dumps(known_models), engineer_id),
                )
        else:
            known_classes = [vessel_class] if vessel_class else []
            known_models = [equipment_model] if equipment_model else []
            await db.execute(
                "INSERT INTO crew_profiles (id, engineer_id, tenant_id, known_vessel_classes, known_equipment_models) VALUES (?, ?, ?, ?, ?)",
                (
                    f"crew-profile-{engineer_id}",
                    engineer_id,
                    tenant_id,
                    json.dumps(known_classes),
                    json.dumps(known_models),
                ),
            )
        await db.commit()


async def insert_message(message_id: str, thread_id: str, role: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (id, thread_id, role, content) VALUES (?, ?, ?, ?)",
            (message_id, thread_id, role, content),
        )
        await db.commit()


async def get_thread_messages(thread_id: str, limit: int = 10) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY timestamp DESC LIMIT ?",
            (thread_id, limit),
        )
        rows = await cursor.fetchall()
        res = [dict(r) for r in rows]
        res.reverse()
        return res
