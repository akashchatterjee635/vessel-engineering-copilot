with open("graph.py", "r", encoding="utf-8") as f:
    content = f.read()

target = "    # 2. Execute wrapped\n    start_time = time.time()"
target_win = target.replace("\n", "\r\n")

replacement = """    # 1.5 Avoidance (Active Failure Suppression)
    if sig_status["status_before"] == "ACTIVE_FAILURE":
        state["cemg_memory_context"] = state.get("cemg_memory_context", "") + f"Skipped tool {tool_name} with params {params} because CEMG memory indicates it is in ACTIVE_FAILURE state.\\n"
        return {"error": "ACTIVE_FAILURE_SUPPRESSED", "message": f"CEMG avoided executing {tool_name} as it recently failed with these parameters."}

    # 2. Execute wrapped
    start_time = time.time()"""

if target in content:
    content = content.replace(target, replacement)
elif target_win in content:
    content = content.replace(target_win, replacement.replace("\n", "\r\n"))
else:
    print("Could not find target")

with open("graph.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
