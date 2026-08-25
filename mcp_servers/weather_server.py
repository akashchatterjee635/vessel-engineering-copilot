import time
import random
from fastmcp import FastMCP

SERVER_START_TIME = time.time()
mcp = FastMCP("marine-weather-voyage-mcp")

@mcp.tool
def get_marine_weather(vessel_id: str) -> dict:
    """Returns realistic marine weather conditions."""
    wind_speed = random.uniform(3, 55)
    wave_height = 0.3 + (wind_speed / 10) * random.uniform(1.0, 1.5)
    sea_state = int(min(9, wave_height))
    
    advisory = "None"
    if wind_speed > 35:
        advisory = "Storm Warning"
    elif random.uniform(0.1, 20.0) < 1.0:
        advisory = "Fog Advisory"
        
    return {
        "vessel_id": vessel_id,
        "wave_height_meters": round(wave_height, 2),
        "wind_speed_knots": round(wind_speed, 1),
        "wind_direction": int(random.uniform(0, 360)),
        "sea_state": sea_state,
        "visibility_nm": round(random.uniform(0.1, 20.0), 2),
        "air_temp_celsius": round(random.uniform(-5.0, 35.0), 1),
        "barometric_pressure_hpa": int(random.uniform(980, 1040)),
        "weather_advisory": advisory
    }

@mcp.tool
def get_voyage_conditions(vessel_id: str) -> dict:
    """Returns current route info."""
    return {
        "vessel_id": vessel_id,
        "current_speed_knots": round(random.uniform(10.0, 24.0), 1),
        "heading": int(random.uniform(0, 360)),
        "estimated_fuel_consumption_mt_day": round(random.uniform(20.0, 60.0), 1),
        "next_waypoint": f"WP-{random.randint(100, 999)}",
        "distance_to_next_port_nm": int(random.uniform(10, 2000))
    }

@mcp.tool
def health_check() -> dict:
    """Returns server status and uptime."""
    uptime_seconds = time.time() - SERVER_START_TIME
    return {
        "server": "marine-weather-voyage-mcp",
        "status": "online",
        "uptime_seconds": round(uptime_seconds, 2)
    }

if __name__ == '__main__':
    mcp.run(transport='http', port=8004)
