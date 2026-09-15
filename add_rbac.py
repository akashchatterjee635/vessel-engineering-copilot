with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """COMMON_STATE = {
    "vessel_id": "vessel-592",
    "vessel_class": "Aframax",
    "engineer_id": "eng-001",
    "tenant_id": "tenant-A",
}"""

replace = """
st.sidebar.title("Login & RBAC Simulator")
selected_role = st.sidebar.selectbox("Role", ["Engineer", "Chief Engineer", "Auditor", "Fleet Admin"])
selected_tenant = st.sidebar.selectbox("Tenant", ["tenant-A", "tenant-B"])

def get_common_state():
    return {
        "vessel_id": "vessel-592" if selected_tenant == "tenant-A" else "vessel-999",
        "vessel_class": "Aframax",
        "engineer_id": "eng-001" if selected_role == "Engineer" else "chief-01",
        "tenant_id": selected_tenant,
        "user_role": selected_role.lower().replace(" ", "_"),
    }
"""
if target in content:
    content = content.replace(target, replace)

state_target = """state = {**COMMON_STATE, "thread_id": st.session_state.thread_id, "user_query": prompt}"""
state_replace = """state = {**get_common_state(), "thread_id": st.session_state.thread_id, "user_query": prompt}"""
if state_target in content:
    content = content.replace(state_target, state_replace)

with open("app.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
