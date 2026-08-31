import asyncio
import os
import uuid

import streamlit as st

# Initialize environment for the dashboard
os.environ["VESSEL_COPILOT_DB"] = "test_vessel_copilot.db"
os.environ["VESSEL_COPILOT_CHECKPOINTS_DB"] = "test_vessel_checkpoints.db"
os.environ["CEMG_SQLITE_PATH"] = "cemg_memory.db"

st.set_page_config(page_title="Vessel Engineering Copilot", page_icon="🚢", layout="wide")

# Handle Streamlit Cloud Secrets
if "OPENAI_API_KEY" in st.secrets:
    os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

# Auto-seed the database if it doesn't exist (useful for Streamlit Cloud)
if not os.path.exists("test_vessel_copilot.db"):
    try:
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), 'tests'))
        import seed
        seed.seed()
    except Exception as e:
        st.error(f"Failed to seed database: {e}")

try:
    from cemg.storage import SqliteStorage
    _cs = SqliteStorage(db_path=os.environ["CEMG_SQLITE_PATH"])
    _cs._init_db()
except Exception:
    pass

import graph as g

# Initialize session state
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Welcome to the MT Test Voyager Engineering Copilot. How can I assist you today?",
        }
    ]

# Common context
COMMON_STATE = {
    "tenant_id": "tenant-001",
    "vessel_id": "vessel-001",
    "vessel_class": "Aframax",
    "engineer_id": "engineer-001",
}


def render_telemetry_dashboard():
    st.sidebar.title("🚢 Live Telemetry")
    st.sidebar.caption("MT Test Voyager - Aframax")

    # Fetch real simulated data
    try:
        telemetry = asyncio.run(g.run_telemetry("tenant-001", "vessel-001", "equip-cargo-pump-001"))
    except Exception:
        telemetry = {"vibration_amplitude": 0.0, "gas_reading_pct_lel": 0.0}

    st.sidebar.subheader("Cargo Pump #1 (ATEX Zone 1)")

    vib = telemetry.get("vibration_amplitude", 6.8)
    gas = telemetry.get("gas_reading_pct_lel", 4.2)

    st.sidebar.metric(
        "Vibration (mm/s)", f"{vib:.1f}", delta=f"{vib - 7.0:.1f}" if vib > 7.0 else "Normal", delta_color="inverse"
    )
    st.sidebar.metric(
        "Gas (LEL %)",
        f"{gas:.1f}%",
        delta="Critical!" if gas > 20 else "Warning" if gas > 10 else "Safe",
        delta_color="inverse",
    )

    if gas > 10:
        st.sidebar.error("⚠️ ATEX GAS HAZARD DETECTED")

    st.sidebar.divider()

    st.sidebar.subheader("Engine Room Aux Pump")
    try:
        aux_telemetry = asyncio.run(g.run_telemetry("tenant-001", "vessel-001", "equip-aux-pump-001"))
    except Exception:
        aux_telemetry = {"vibration_amplitude": 0.0, "gas_reading_pct_lel": 0.0}

    vib2 = aux_telemetry.get("vibration_amplitude", 2.1)
    st.sidebar.metric("Vibration (mm/s)", f"{vib2:.1f}")

    st.sidebar.divider()
    
    if st.sidebar.button("🔄 New Session / Reset"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = [
            {"role": "assistant", "content": "Welcome to the MT Test Voyager Engineering Copilot. How can I assist you today?"}
        ]
        st.rerun()
def main():
    render_telemetry_dashboard()

    st.title("Vessel Engineering Copilot")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask a question or log an entry..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Processing..."):
                cfg = {"configurable": {"thread_id": st.session_state.thread_id}}
                state = {**COMMON_STATE, "thread_id": st.session_state.thread_id, "user_query": prompt}
                
                async def _run_graph():
                    # Run graph in a single event loop to prevent lock errors
                    res = await g.app.ainvoke(state, config=cfg)
                    # Handle HITL pause (ActionAgent interrupt)
                    if res is None or not res.get("final_synthesis"):
                        res = await g.app.ainvoke(None, config=cfg)
                    return res
                
                try:
                    result = asyncio.run(_run_graph())
                    
                    synthesis = result.get("final_synthesis", {}).get("evaluation", "")
                    if not synthesis and result.get("logbook_result"):
                        synthesis = "Logbook entry successfully recorded."
                        
                except Exception as e:
                    synthesis = f"Error processing query: {str(e)}"
                    result = {}

                st.markdown(synthesis)
                st.session_state.messages.append({"role": "assistant", "content": synthesis})

                with st.expander("Diagnostic Trace"):
                    st.json(result.get("triage_decision", {}))


if __name__ == "__main__":
    main()
