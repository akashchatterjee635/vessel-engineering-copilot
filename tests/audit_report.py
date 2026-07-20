import sqlite3
import os

DB_PATH = os.environ.get("VESSEL_COPILOT_DB", "test_vessel_copilot.db")

def print_audit_report():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file '{DB_PATH}' not found. Please run seed.py and test_harness.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    print("=" * 60)
    print("               LLMOps AUDIT & PERFORMANCE REPORT")
    print("=" * 60)
    
    # 1. Total token counts and cost estimation
    cur = conn.execute("""
        SELECT 
            SUM(prompt_tokens) as total_prompt_tokens,
            SUM(completion_tokens) as total_completion_tokens,
            SUM(estimated_cost) as total_cost,
            COUNT(*) as total_calls
        FROM tool_call_audit
        WHERE tool_name = 'openai_llm'
    """)
    row = cur.fetchone()
    if row and row["total_calls"] > 0:
        total_prompt = row["total_prompt_tokens"] or 0
        total_completion = row["total_completion_tokens"] or 0
        total_cost = row["total_cost"] or 0.0
        total_calls = row["total_calls"]
        print(f"LLM API Telemetry Metrics:")
        print(f"  Total LLM Invocations:       {total_calls}")
        print(f"  Total Prompt Tokens:         {total_prompt}")
        print(f"  Total Completion Tokens:     {total_completion}")
        print(f"  Total Combined Tokens:       {total_prompt + total_completion}")
        print(f"  Total Estimated Cost (USD):  ${total_cost:.5f}")
    else:
        print("No LLM API calls recorded in audit.")
        
    print("-" * 60)
    
    # 2. Node Latency Metrics
    print("Latency Metrics by Node / Agent:")
    cur = conn.execute("""
        SELECT 
            agent_name,
            COUNT(*) as occurrences,
            AVG(latency_ms) as avg_latency_ms,
            MAX(latency_ms) as max_latency_ms
        FROM tool_call_audit
        GROUP BY agent_name
        ORDER BY avg_latency_ms DESC
    """)
    rows = cur.fetchall()
    for r in rows:
        print(f"  [{r['agent_name']}]:")
        print(f"    Invocations: {r['occurrences']}")
        print(f"    Avg Latency: {r['avg_latency_ms']:.1f} ms")
        print(f"    Max Latency: {r['max_latency_ms']} ms")
        
    print("-" * 60)
    
    # 3. Triage / Routing Efficiency Gating
    # Firing efficiency: what percentage of tools requested by the Triage Router were actually used in final Synthesis
    # Let's count how many times gate_fired was 1, and how many times is_used_by_synthesis was 1.
    cur = conn.execute("""
        SELECT 
            tool_name,
            SUM(gate_fired) as gates_fired,
            SUM(is_used_by_synthesis) as used_in_synthesis
        FROM tool_call_audit
        WHERE tool_name NOT IN ('openai_llm', 'logbook_extractor', 'crew_profile_lookup', 'checklist_lookup')
        GROUP BY tool_name
    """)
    rows = cur.fetchall()
    if rows:
        print("Triage Routing Efficiency:")
        for r in rows:
            fired = r["gates_fired"] or 0
            used = r["used_in_synthesis"] or 0
            efficiency = (used / fired * 100) if fired > 0 else 0.0
            print(f"  Tool [{r['tool_name']}]:")
            print(f"    Times Requested by Triage: {fired}")
            print(f"    Times Used in Synthesis:   {used}")
            print(f"    Utilization Efficiency:     {efficiency:.1f}%")
    else:
        print("No tool call routing data found.")
        
    print("=" * 60)
    conn.close()

if __name__ == "__main__":
    print_audit_report()
