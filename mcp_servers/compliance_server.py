import random
import time
from datetime import datetime, timedelta

from fastmcp import FastMCP

SERVER_START_TIME = time.time()
mcp = FastMCP("vessel-compliance-mcp")


@mcp.tool
def verify_class_compliance(vessel_id: str, system_category: str) -> dict:
    """Returns compliance status against classification society rules."""
    rules = [
        "DNV-GL Rules for Classification (Part 4 Ch.6 for rotating machinery)",
        "SOLAS Chapter II-2 (fire safety)",
        "SOLAS Chapter III (life-saving)",
        "MARPOL Annex VI (emissions)",
    ]
    statuses = ["Compliant", "Non-Compliant", "Conditional"]
    findings_list = [
        "No issues found.",
        "Minor corrosion on casing.",
        "Missing latest calibration certificate.",
        "Pressure relief valve test overdue.",
    ]

    return {
        "vessel_id": vessel_id,
        "system_category": system_category,
        "rule_reference": random.choice(rules),
        "status": random.choice(statuses),
        "next_survey_due": (datetime.utcnow() + timedelta(days=random.randint(30, 365))).strftime("%Y-%m-%d"),
        "last_survey_date": (datetime.utcnow() - timedelta(days=random.randint(30, 365))).strftime("%Y-%m-%d"),
        "findings": random.sample(findings_list, k=random.randint(1, 2)),
    }


@mcp.tool
def get_regulatory_requirements(vessel_class: str, zone_class: str) -> dict:
    """Returns applicable ATEX Directive (2014/34/EU) requirements for zone classification."""
    return {
        "vessel_class": vessel_class,
        "zone_class": zone_class,
        "directive": "ATEX Directive (2014/34/EU)",
        "equipment_certification_requirements": ["Ex d", "Ex e", "Ex ia", "Ex ib"],
        "inspection_intervals": "Every 12 months",
        "permitted_maintenance_actions": [
            "Visual inspection",
            "Non-intrusive testing",
            "Calibration",
        ],
    }


@mcp.tool
def health_check() -> dict:
    """Returns server status and uptime."""
    uptime_seconds = time.time() - SERVER_START_TIME
    return {
        "server": "vessel-compliance-mcp",
        "status": "online",
        "uptime_seconds": round(uptime_seconds, 2),
    }


if __name__ == "__main__":
    mcp.run(transport="http", port=8002)
