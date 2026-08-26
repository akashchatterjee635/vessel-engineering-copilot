import os
import sqlite3
import time

from fastmcp import FastMCP

SERVER_START_TIME = time.time()
mcp = FastMCP("vessel-pms-history-mcp")

DB_PATH = os.environ.get("VESSEL_COPILOT_DB", "test_vessel_copilot.db")


@mcp.tool
def get_equipment_history(equipment_id: str, limit: int = 10) -> dict:
    """Returns history of logs for a specific equipment ID."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipment_logs'")
        if not cursor.fetchone():
            return {"error": "Table equipment_logs does not exist", "results": []}

        cursor.execute(
            "SELECT * FROM equipment_logs WHERE equipment_id = ? ORDER BY timestamp DESC LIMIT ?",
            (equipment_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append(
                {
                    "raw_entry": row["raw_entry"],
                    "structured_summary": row["structured_summary"],
                    "log_type": row["log_type"],
                    "timestamp": row["timestamp"],
                }
            )
        return {"equipment_id": equipment_id, "results": results}
    except Exception as e:
        return {"error": str(e), "results": []}


@mcp.tool
def search_manuals(vessel_class: str, equipment_id: str, query: str) -> dict:
    """Searches manual documents matching the query keywords."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'")
        if not cursor.fetchone():
            return {"error": "Table documents does not exist", "results": []}

        cursor.execute("SELECT * FROM documents")
        rows = cursor.fetchall()
        conn.close()

        terms = query.lower().split()
        scored_docs = []

        for row in rows:
            title = (row["title"] or "").lower()
            content = (row["content"] or "").lower()
            score = 0
            for term in terms:
                score += title.count(term) * 2  # Title hits weighted more
                score += content.count(term)
            if score > 0:
                scored_docs.append(
                    {
                        "title": row["title"],
                        "content": row["content"][:500] if row["content"] else "",
                        "section_name": row["section_name"] if "section_name" in row.keys() else "",
                        "relevance_score": score,
                    }
                )

        scored_docs.sort(key=lambda x: x["relevance_score"], reverse=True)
        return {"query": query, "results": scored_docs[:5]}
    except Exception as e:
        return {"error": str(e), "results": []}


@mcp.tool
def health_check() -> dict:
    """Returns server status and uptime."""
    uptime_seconds = time.time() - SERVER_START_TIME
    return {
        "server": "vessel-pms-history-mcp",
        "status": "online",
        "uptime_seconds": round(uptime_seconds, 2),
        "db_path": DB_PATH,
    }


if __name__ == "__main__":
    mcp.run(transport="http", port=8003)
