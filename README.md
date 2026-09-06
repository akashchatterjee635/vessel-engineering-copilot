# Vessel Engineering Copilot

A tenant-aware, multi-agent AI platform for ship's crew — built with **LangGraph**, **FastMCP** remote tool servers, and async parallel execution. 

## Architecture

```text
                          ┌─────────────────────────┐
                          │    FastMCP Servers       │
                          │                          │
                          │  :8001 Telemetry MCP     │
                          └──────────┬──────────────┘
                                     │ MCP Protocol
                          ┌──────────▼──────────────┐
                          │   MCPClientManager       │
                          │   (graph.py)             │
                          └──────────┬──────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                        LangGraph Orchestrator                          │
│                                                                        │
│  __start__ → TriageRouter → ResolveEquipment                           │
│                  │                                │                     │
│          (blocked queries)              DocumentRetriever               │
│                  │                                │                     │
│                  ▼                        ATEXHazardCheck               │
│            SynthesisAgent                        │                     │
│                                    ┌─────────────┼──────────┐          │
│                                    ▼             ▼          ▼          │
│                              Logbook      Onboarding    Checklist      │
│                              Extraction   Compat.       Agent          │
│                                    │             │          │          │
│                              FanOutOrchestrator (CEMG-wrapped)         │
│                                    │                                   │
│                              SynthesisAgent                            │
│                                    │                                   │
│                              OutputGuardrail                           │
│                                    │                                   │
│                              ActionAgent (HITL pause)                  │
│                                    │                                   │
│                              ProfileConsolidation                      │
│                                    │                                   │
│                                AuditNode → END                         │
└────────────────────────────────────────────────────────────────────────┘
```

## Core Capabilities

### Enterprise AI Knowledge Platform
- **Advanced RAG**: Retrieves equipment manuals, safety standards, and troubleshooting guides
- **Output Guardrails**: Enforces mandatory ATEX safety warnings when gas hazards are active
- **LLMOps**: Token counting, cost estimation, triage utilization audit

### Autonomous Multi-Agent AI Platform
- **Streamlit UI**: Real-time telemetry dashboard + Copilot Chat interface
- **FastMCP Integration**: Telemetry MCP server with realistic maritime data simulation
- **CEMG Memory**: Causal Experience Memory Graph for tool failure avoidance
- **Persistent HITL**: Interactive UI for Work Order approval/rejection gates
- **Deterministic Action Policy**: Strict rules block automated actions in safety-critical ATEX zones

## Project Structure

```
vessel-engineering-copilot/
├── app.py                      # Streamlit Frontend + Async loop management
├── graph.py                    # LangGraph orchestrator + MCPClientManager
├── db.py                       # Async SQLite data-access layer
├── schema.sql                  # Tenant-aware database schema
├── requirements.txt            # Production dependencies
├── .env.example                # Environment variable template
├── Dockerfile                  # Main app container
├── Dockerfile.mcp              # MCP server container (parameterized)
├── docker-compose.yml          # Full stack: app + Telemetry MCP
│
├── mcp_servers/                # FastMCP remote tool servers
│   └── telemetry_server.py     # Port 8001 — machinery vibration, gas readings
│
├── mlops/                      # MLOps infrastructure
│   ├── model_config.yaml       # Centralized model/guardrail/feature config
│   └── eval_tracker.py         # Evaluation regression tracker
│
├── tests/                      # Test suites
│   ├── seed.py                 # Database seeding script
│   ├── test_harness.py         # End-to-end integration tests (7 scenarios)
│   ├── test_mcp_servers.py     # MCP server integration tests
│   ├── run_evals.py            # Guardrail/RAG/CEMG evaluation assertions
│   ├── audit_report.py         # LLMOps metrics reporting CLI
│   └── render_graph.py         # Workflow diagram generator
│
└── .github/workflows/          # CI/CD pipelines
    ├── ci.yml                  # Lint + test + build + eval regression
    └── deploy.yml              # Docker compose deployment
```

## Quick Start

### Option 1: Local Development (without MCP servers)

```bash
python -m venv venv
.\venv\Scripts\activate          # Windows
pip install -r requirements.txt
pip install -e ../cemg           # Install sibling CEMG package

python tests/seed.py             # Create and seed test database
python tests/test_harness.py     # Run all 7 scenarios (mocks only)
python tests/audit_report.py     # View LLMOps metrics
```

### Option 2: Full Stack with Docker (MCP servers enabled)

```bash
# Build and start all services
docker-compose up --build -d

# Verify health
curl http://localhost:8001/mcp   # Telemetry MCP
```

### Option 3: Run Individual MCP Servers

```bash
# Start a single MCP server for development
python -m mcp_servers.telemetry_server       # Port 8001
python -m mcp_servers.compliance_server      # Port 8002
python -m mcp_servers.history_server         # Port 8003
python -m mcp_servers.weather_server         # Port 8004
python -m mcp_servers.port_services_server   # Port 8005
```

## Configuration

All configuration is centralized in [`mlops/model_config.yaml`](mlops/model_config.yaml):

- **Model settings**: Name, temperature, token costs
- **Guardrail thresholds**: ATEX LEL limits, bypass keyword lists
- **Feature flags**: MCP servers, CEMG, RAG, Prometheus toggles
- **MCP server URLs**: Endpoint configuration with timeouts

Environment variables override YAML config. See [`.env.example`](.env.example) for all options.

## Monitoring

When `prometheus_enabled: true` in `model_config.yaml`:

- **Prometheus** scrapes metrics from `:9090/metrics` (copilot) and each MCP server
- **Grafana** dashboard at `mlops/grafana/dashboard.json` visualizes:
  - LLM token usage and cost burn rate
  - Tool latency heatmap per MCP server
  - Guardrail block rates
  - ATEX alert frequency
  - CEMG failure avoidance rates

## CI/CD

GitHub Actions pipelines at `.github/workflows/`:

- **`ci.yml`**: Runs on every push/PR — linting (ruff), unit tests, Docker build validation, eval regression checks
- **`deploy.yml`**: Deploys the full Docker Compose stack with smoke tests
