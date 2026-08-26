import random
import time
from datetime import datetime, timedelta

from fastmcp import FastMCP

SERVER_START_TIME = time.time()
mcp = FastMCP("vessel-telemetry-mcp")


@mcp.tool
def get_machinery_telemetry(vessel_id: str, equipment_id: str) -> dict:
    """Returns realistic machinery telemetry data (vibration, temp, pressure, RPM)."""
    is_pump = "pump" in equipment_id.lower()
    is_gen = "gen" in equipment_id.lower()
    is_comp = "comp" in equipment_id.lower()

    rpm_min, rpm_max = 800, 3600
    if is_pump:
        rpm_min, rpm_max = 1400, 1800
    elif is_gen:
        rpm_min, rpm_max = 720, 1800
    elif is_comp:
        rpm_min, rpm_max = 1200, 3000

    return {
        "vessel_id": vessel_id,
        "equipment_id": equipment_id,
        "timestamp": datetime.utcnow().isoformat(),
        "vibration_rms_mms": round(random.uniform(0.5, 12.0), 2),
        "vibration_frequency_band": random.choice(["low", "mid", "high"]),
        "bearing_temperature_c": round(random.uniform(40.0, 95.0), 1),
        "oil_pressure_bar": round(random.uniform(1.5, 4.5), 2),
        "rpm": int(random.uniform(rpm_min, rpm_max)),
    }


@mcp.tool
def get_gas_hazard_status(vessel_id: str, equipment_id: str) -> dict:
    """Returns gas hazard readings (LEL, H2S, O2) for a given equipment zone."""
    rand_val = random.random()
    if rand_val < 0.80:
        gas_reading_pct_lel = random.uniform(0.0, 4.9)
    elif rand_val < 0.95:
        gas_reading_pct_lel = random.uniform(5.0, 20.0)
    else:
        gas_reading_pct_lel = random.uniform(20.1, 30.0)

    return {
        "vessel_id": vessel_id,
        "equipment_id": equipment_id,
        "timestamp": datetime.utcnow().isoformat(),
        "gas_reading_pct_lel": round(gas_reading_pct_lel, 2),
        "h2s_ppm": int(random.uniform(0, 15)),
        "o2_pct": round(random.uniform(19.5, 21.0), 2),
        "detection_zone": f"Zone-{random.randint(1, 5)}",
        "last_calibration_date": (datetime.utcnow() - timedelta(days=random.randint(10, 180))).strftime("%Y-%m-%d"),
    }


@mcp.tool
def health_check() -> dict:
    """Returns server status and uptime."""
    uptime_seconds = time.time() - SERVER_START_TIME
    return {
        "server": "vessel-telemetry-mcp",
        "status": "online",
        "uptime_seconds": round(uptime_seconds, 2),
    }


if __name__ == "__main__":
    mcp.run(transport="http", port=8001)
