import asyncio
import os
import time
import uuid

import streamlit as st


def stream_string(text: str, delay: float = 0.04):
    words = text.split(" ")
    for i, word in enumerate(words):
        yield word + (" " if i < len(words) - 1 else "")
        time.sleep(delay)


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

        sys.path.append(os.path.join(os.path.dirname(__file__), "tests"))
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
            {
                "role": "assistant",
                "content": "Welcome to the MT Test Voyager Engineering Copilot. How can I assist you today?",
            }
        ]
        st.rerun()


def main():
    render_telemetry_dashboard()

    st.title("Vessel Engineering Copilot")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    cfg = {"configurable": {"thread_id": st.session_state.thread_id}}

    async def _check_status():
        try:
            return await g.app.aget_state(cfg)
        except Exception:
            return None

    graph_state = asyncio.run(_check_status())
    is_paused = graph_state and graph_state.next and "ActionAgent" in graph_state.next

    if is_paused:
        st.warning("⏸ **WORK ORDER APPROVAL REQUIRED**")
        st.info(
            "The system has proposed creating a work order. Please review the recommendation above and approve or reject it."
        )

        col1, col2 = st.columns(2)
        if col1.button("✅ Approve Work Order", use_container_width=True):

            async def _approve():
                await g.app.aupdate_state(
                    cfg, {"triage_decision": {**graph_state.values["triage_decision"], "human_approval": "approved"}}
                )
                return await g.app.ainvoke(None, config=cfg)

            with st.spinner("Executing..."):
                res = asyncio.run(_approve())
            st.session_state.messages.append(
                {"role": "assistant", "content": "✅ **Work Order Approved and Executed.**"}
            )
            st.rerun()

        if col2.button("❌ Reject", type="primary", use_container_width=True):

            async def _reject():
                await g.app.aupdate_state(
                    cfg, {"triage_decision": {**graph_state.values["triage_decision"], "human_approval": "rejected"}}
                )
                return await g.app.ainvoke(None, config=cfg)

            with st.spinner("Canceling..."):
                res = asyncio.run(_reject())
            reason = res.get("action_rejection_reason", "Human rejected work order.")
            st.session_state.messages.append(
                {"role": "assistant", "content": f"❌ **Work Order Rejected.** No action was taken. ({reason})"}
            )
            st.rerun()

        return  # Block chat input while approval is pending

    if prompt := st.chat_input("Ask a question or log an entry..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            status_container = st.status("Orchestrating agents...", expanded=True)

            state = {**COMMON_STATE, "thread_id": st.session_state.thread_id, "user_query": prompt}

            async def _run_graph():
                final_result = None
                async for chunk in g.app.astream(state, config=cfg):
                    for node_name, node_state in chunk.items():
                        status_container.write(f"Executing step: **{node_name}**")
                        final_result = node_state
                return final_result

            try:
                result = asyncio.run(_run_graph())
                status_container.update(label="Graph execution complete", state="complete", expanded=False)

                # If it paused immediately on this turn (e.g., ActionAgent), don't process final_synthesis yet
                # We will re-render and hit the `is_paused` block above
                new_graph_state = asyncio.run(_check_status())
                if new_graph_state and new_graph_state.next and "ActionAgent" in new_graph_state.next:
                    synthesis = result.get("final_synthesis", {}).get("evaluation", "")
                    if synthesis:
                        st.write_stream(stream_string(synthesis))
                        st.session_state.messages.append({"role": "assistant", "content": synthesis})
                    st.rerun()

                synthesis = result.get("final_synthesis", {}).get("evaluation", "")
                if not synthesis and result.get("logbook_result"):
                    synthesis = "Logbook entry successfully recorded."

            except Exception as e:
                status_container.update(label="Graph execution failed", state="error", expanded=True)
                synthesis = f"Error processing query: {str(e)}"
                result = {}

            if synthesis:
                st.write_stream(stream_string(synthesis))

            st.session_state.messages.append({"role": "assistant", "content": synthesis})

            with st.expander("Diagnostic Trace"):
                st.json(result.get("triage_decision", {}))


if __name__ == "__main__":
    main()
