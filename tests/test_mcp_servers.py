"""
Unit tests for FastMCP remote servers.

Tests each MCP server in isolation by connecting to it as a client,
calling its tools, and validating response schemas and data ranges.

Usage:
    # Start MCP servers first:
    docker-compose up -d mcp-telemetry mcp-compliance mcp-history mcp-weather mcp-port-services

    # Then run:
    pytest tests/test_mcp_servers.py -v
"""

import json
import os

import pytest

# Skip entire module if fastmcp is not installed
pytest.importorskip("fastmcp")

from fastmcp import Client as MCPClient

# --- Server URL configuration ---
MCP_TELEMETRY_URL = os.environ.get("MCP_TELEMETRY_URL", "http://localhost:8001/mcp")
MCP_COMPLIANCE_URL = os.environ.get("MCP_COMPLIANCE_URL", "http://localhost:8002/mcp")
MCP_HISTORY_URL = os.environ.get("MCP_HISTORY_URL", "http://localhost:8003/mcp")
MCP_WEATHER_URL = os.environ.get("MCP_WEATHER_URL", "http://localhost:8004/mcp")
MCP_PORT_SERVICES_URL = os.environ.get("MCP_PORT_SERVICES_URL", "http://localhost:8005/mcp")

LIVE_MCP = os.environ.get("LIVE_MCP", "false").lower() == "true"
skip_unless_live = pytest.mark.skipif(not LIVE_MCP, reason="Set LIVE_MCP=true to run MCP server tests")


async def call_mcp_tool(url: str, tool_name: str, arguments: dict) -> dict:
    """Helper to call a tool on a remote MCP server and parse the JSON response."""
    async with MCPClient(url) as client:
        result = await client.call_tool(tool_name, arguments)
        for item in result:
            if hasattr(item, "text"):
                return json.loads(item.text)
        return {}


# --- Telemetry Server Tests ---


@skip_unless_live
class TestTelemetryServer:
    @pytest.mark.asyncio
    async def test_health_check(self):
        result = await call_mcp_tool(MCP_TELEMETRY_URL, "health_check", {})
        assert result["status"] == "healthy"
        assert "uptime_seconds" in result

    @pytest.mark.asyncio
    async def test_get_machinery_telemetry(self):
        result = await call_mcp_tool(
            MCP_TELEMETRY_URL,
            "get_machinery_telemetry",
            {"vessel_id": "vessel-001", "equipment_id": "equip-aux-pump-001"},
        )
        assert "vibration_amplitude" in result
        assert 0.0 <= result["vibration_amplitude"] <= 15.0
        assert result["frequency_band"] in ("low", "mid", "high")
        assert "bearing_temperature_celsius" in result
        assert "oil_pressure_bar" in result

    @pytest.mark.asyncio
    async def test_get_gas_hazard_status(self):
        result = await call_mcp_tool(
            MCP_TELEMETRY_URL,
            "get_gas_hazard_status",
            {"vessel_id": "vessel-001", "equipment_id": "equip-cargo-pump-001"},
        )
        assert "gas_reading_pct_lel" in result
        assert 0.0 <= result["gas_reading_pct_lel"] <= 35.0
        assert "h2s_ppm" in result
        assert "o2_pct" in result


# --- Compliance Server Tests ---


@skip_unless_live
class TestComplianceServer:
    @pytest.mark.asyncio
    async def test_health_check(self):
        result = await call_mcp_tool(MCP_COMPLIANCE_URL, "health_check", {})
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_verify_class_compliance(self):
        result = await call_mcp_tool(
            MCP_COMPLIANCE_URL,
            "verify_class_compliance",
            {"vessel_id": "vessel-001", "system_category": "rotating_machinery"},
        )
        assert "status" in result
        assert result["status"] in ("Compliant", "Non-Compliant", "Conditional")
        assert "rule_reference" in result

    @pytest.mark.asyncio
    async def test_get_regulatory_requirements(self):
        result = await call_mcp_tool(
            MCP_COMPLIANCE_URL,
            "get_regulatory_requirements",
            {"vessel_class": "Aframax", "zone_class": "Zone 1"},
        )
        assert "atex_directive" in result
        assert "equipment_certifications" in result


# --- History Server Tests ---


@skip_unless_live
class TestHistoryServer:
    @pytest.mark.asyncio
    async def test_health_check(self):
        result = await call_mcp_tool(MCP_HISTORY_URL, "health_check", {})
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_equipment_history(self):
        result = await call_mcp_tool(
            MCP_HISTORY_URL,
            "get_equipment_history",
            {"equipment_id": "equip-aux-pump-001", "limit": 5},
        )
        assert "logs" in result or "previous_logs" in result

    @pytest.mark.asyncio
    async def test_search_manuals(self):
        result = await call_mcp_tool(
            MCP_HISTORY_URL,
            "search_manuals",
            {
                "vessel_class": "Aframax",
                "equipment_id": "equip-aux-pump-001",
                "query": "grinding noise pump vibration",
            },
        )
        assert "documents" in result or "results" in result


# --- Weather Server Tests ---


@skip_unless_live
class TestWeatherServer:
    @pytest.mark.asyncio
    async def test_health_check(self):
        result = await call_mcp_tool(MCP_WEATHER_URL, "health_check", {})
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_marine_weather(self):
        result = await call_mcp_tool(MCP_WEATHER_URL, "get_marine_weather", {"vessel_id": "vessel-001"})
        assert "wave_height_meters" in result
        assert "wind_speed_knots" in result
        assert "sea_state" in result
        assert 0 <= result["sea_state"] <= 9

    @pytest.mark.asyncio
    async def test_get_voyage_conditions(self):
        result = await call_mcp_tool(MCP_WEATHER_URL, "get_voyage_conditions", {"vessel_id": "vessel-001"})
        assert "current_speed_knots" in result
        assert "heading" in result


# --- Port Services Server Tests ---


@skip_unless_live
class TestPortServicesServer:
    @pytest.mark.asyncio
    async def test_health_check(self):
        result = await call_mcp_tool(MCP_PORT_SERVICES_URL, "health_check", {})
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_port_services(self):
        result = await call_mcp_tool(MCP_PORT_SERVICES_URL, "get_port_services", {"vessel_id": "vessel-001"})
        assert "port_name" in result
        assert "available_services" in result

    @pytest.mark.asyncio
    async def test_get_berth_availability(self):
        result = await call_mcp_tool(MCP_PORT_SERVICES_URL, "get_berth_availability", {"port_code": "NLRTM"})
        assert "berths" in result or "berth_slots" in result
