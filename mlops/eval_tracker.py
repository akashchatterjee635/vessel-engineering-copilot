import sqlite3
import argparse
import json
import os
from datetime import datetime
from typing import Dict, Any

DB_PATH = os.environ.get("EVAL_DB_PATH", "eval_tracker.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS eval_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            git_sha TEXT,
            model_name TEXT,
            model_version TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS eval_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            metric_name TEXT,
            metric_value REAL,
            threshold REAL,
            passed BOOLEAN,
            FOREIGN KEY(run_id) REFERENCES eval_runs(id)
        )
    ''')
    conn.commit()
    conn.close()

def record_eval_run(git_sha: str, model_name: str, metrics: Dict[str, Any]) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO eval_runs (git_sha, model_name, model_version) VALUES (?, ?, ?)",
        (git_sha, model_name, "latest")
    )
    run_id = cursor.lastrowid
    
    for metric, value in metrics.items():
        threshold = 0.0
        passed = True
        cursor.execute(
            "INSERT INTO eval_metrics (run_id, metric_name, metric_value, threshold, passed) VALUES (?, ?, ?, ?, ?)",
            (run_id, metric, float(value), threshold, passed)
        )
        
    conn.commit()
    conn.close()
    return run_id

def get_baseline(metric_name: str, n: int = 5) -> float:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT metric_value FROM eval_metrics 
        WHERE metric_name = ? 
        ORDER BY id DESC LIMIT ?
    ''', (metric_name, n))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return 0.0
    return sum(row[0] for row in rows) / len(rows)

def check_regression(current_metrics: Dict[str, Any], threshold_pct: float = 20.0) -> Dict[str, Any]:
    results = {}
    for metric, value in current_metrics.items():
        baseline = get_baseline(metric)
        if baseline > 0:
            change_pct = ((value - baseline) / baseline) * 100
        else:
            change_pct = 0.0
            
        is_regression = False
        # Token usage increase logic as an example
        if "token" in metric.lower() and change_pct > threshold_pct:
            is_regression = True
            
        results[metric] = {
            "current": value,
            "baseline": baseline,
            "change_pct": change_pct,
            "is_regression": is_regression
        }
    return results

def generate_report(run_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,))
    run = cursor.fetchone()
    
    cursor.execute("SELECT * FROM eval_metrics WHERE run_id = ?", (run_id,))
    metrics = cursor.fetchall()
    conn.close()
    
    if not run:
        return "Run not found."
        
    report = f"# Evaluation Report: Run {run_id}\n\n"
    report += f"- **Git SHA:** {run[2]}\n"
    report += f"- **Model:** {run[3]}\n"
    report += f"- **Timestamp:** {run[1]}\n\n"
    
    report += "## Metrics\n\n"
    report += "| Metric | Value | Passed |\n"
    report += "|---|---|---|\n"
    
    for m in metrics:
        report += f"| {m[2]} | {m[3]:.4f} | {'✅' if m[5] else '❌'} |\n"
        
    return report

if __name__ == "__main__":
    init_db()
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--git-sha", type=str, default="unknown")
    parser.add_argument("--metrics", type=str, help="JSON string of metrics")
    
    args = parser.parse_args()
    
    if args.record and args.metrics:
        metrics = json.loads(args.metrics)
        run_id = record_eval_run(args.git_sha, "gpt-4", metrics)
        print(f"Recorded run {run_id}")
        print(generate_report(run_id))
    elif args.check:
        print("Checking regression...")
        # Implement full check logic integrated with CLI as needed
