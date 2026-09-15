with open("db.py", "r", encoding="utf-8") as f:
    content = f.read()

# Update get_crew_profile
q1 = '"SELECT * FROM crew_profiles WHERE engineer_id = ? ORDER BY updated_at DESC LIMIT 1"'
r1 = '"SELECT * FROM crew_profiles WHERE engineer_id = ? AND tenant_id = ? ORDER BY updated_at DESC LIMIT 1"'
content = content.replace(q1, r1)
content = content.replace(
    'await db.execute(\n            "SELECT * FROM crew_profiles WHERE engineer_id = ? AND tenant_id = ? ORDER BY updated_at DESC LIMIT 1",\n            (engineer_id,),',
    'await db.execute(\n            "SELECT * FROM crew_profiles WHERE engineer_id = ? AND tenant_id = ? ORDER BY updated_at DESC LIMIT 1",\n            (engineer_id, tenant_id),',
)

# Update update_crew_profile
q2 = 'cursor = await db.execute("SELECT * FROM crew_profiles WHERE engineer_id = ?", (engineer_id,))'
r2 = 'cursor = await db.execute("SELECT * FROM crew_profiles WHERE engineer_id = ? AND tenant_id = ?", (engineer_id, tenant_id))'
content = content.replace(q2, r2)
content = content.replace(
    'WHERE engineer_id = ?",\n                    (json.dumps(known_classes), json.dumps(known_models), engineer_id),',
    'WHERE engineer_id = ? AND tenant_id = ?",\n                    (json.dumps(known_classes), json.dumps(known_models), engineer_id, tenant_id),',
)

with open("db.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
