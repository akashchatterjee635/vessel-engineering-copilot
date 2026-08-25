import time
import random
from datetime import datetime, timedelta
from fastmcp import FastMCP

SERVER_START_TIME = time.time()
mcp = FastMCP("marine-port-services-mcp")

PORTS = ["Rotterdam", "Singapore", "Fujairah", "Houston", "Piraeus", "Shanghai", "Los Angeles"]

@mcp.tool
def get_port_services(vessel_id: str) -> dict:
    """Returns available services for a port."""
    port_name = random.choice(PORTS)
    services = [
        "bunkering (IFO380, VLSFO, MGO)", 
        "spare_parts_depot", 
        "drydock", 
        "crew_change", 
        "waste_reception", 
        "fresh_water", 
        "provisions"
    ]
    
    return {
        "vessel_id": vessel_id,
        "port": port_name,
        "available_services": random.sample(services, k=random.randint(3, len(services))),
        "contact_vhf_channel": random.choice([12, 14, 16, 71, 72]),
        "agent_name": f"Agent {random.choice(['Smith', 'Wong', 'Garcia', 'Müller', 'Lee'])}",
        "estimated_wait_time_hours": round(random.uniform(0.5, 48.0), 1)
    }

@mcp.tool
def get_berth_availability(port_code: str) -> dict:
    """Returns berth slots availability, restrictions, and tidal windows."""
    now = datetime.utcnow()
    berths = []
    for i in range(random.randint(1, 3)):
        start = now + timedelta(hours=random.uniform(1, 72))
        end = start + timedelta(hours=random.uniform(12, 48))
        berths.append({
            "berth_id": f"B-{random.randint(1, 20)}",
            "available_from": start.isoformat(),
            "available_to": end.isoformat(),
            "draft_restriction_meters": round(random.uniform(8.0, 16.0), 1),
            "max_loa_meters": int(random.uniform(150, 400)),
            "tidal_windows": f"{start.strftime('%H:%M')} to {(start + timedelta(hours=4)).strftime('%H:%M')}"
        })
        
    return {
        "port_code": port_code,
        "berths": berths
    }

@mcp.tool
def health_check() -> dict:
    """Returns server status and uptime."""
    uptime_seconds = time.time() - SERVER_START_TIME
    return {
        "server": "marine-port-services-mcp",
        "status": "online",
        "uptime_seconds": round(uptime_seconds, 2)
    }

if __name__ == '__main__':
    mcp.run(transport='http', port=8005)
