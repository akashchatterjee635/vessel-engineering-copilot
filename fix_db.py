with open("db.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    "async def get_crew_profile(engineer_id: str) -> dict[str, Any] | None:",
    "async def get_crew_profile(engineer_id: str, tenant_id: str) -> dict[str, Any] | None:",
)
content = content.replace("(engineer_id,)", "(engineer_id, tenant_id)")

with open("db.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)

with open("graph.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'profile = await db.get_crew_profile(state["engineer_id"])',
    'profile = await db.get_crew_profile(state["engineer_id"], state["tenant_id"])',
)

with open("graph.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
