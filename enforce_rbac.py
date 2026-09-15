with open("graph.py", "r", encoding="utf-8") as f:
    content = f.read()

state_target = """    tenant_id: str
    vessel_id: str"""
state_replace = """    tenant_id: str
    vessel_id: str
    user_role: str"""
content = content.replace(state_target, state_replace)

action_target = """async def action_agent(state: AgentState) -> dict[str, Any]:
    decision = state.get("triage_decision")"""
action_replace = """async def action_agent(state: AgentState) -> dict[str, Any]:
    if state.get("user_role") not in ["chief_engineer", "fleet_admin"]:
        return {"action_rejection_reason": "RBAC ERROR: Only a Chief Engineer can approve work orders."}
        
    decision = state.get("triage_decision")"""
content = content.replace(action_target, action_replace)

# Also check tenant isolation in DB layer (it's already checked in db.py for some methods, but I'll add a comment in docstring)

with open("graph.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
