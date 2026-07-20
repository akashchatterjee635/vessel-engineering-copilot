# Vessel Engineering Copilot

A multi-tenant, multi-agent AI Assistant for ship's crew, engineered to serve as both an **Enterprise AI Knowledge Platform** and an **Autonomous Multi-Agent AI Platform**. Built with LangGraph, MCP tool connections, and async parallel execution, it helps crew diagnose machinery issues, onboard onto unfamiliar vessel classes, log maintenance, and safely navigate ATEX hazard zones.

## Core Capabilities Added

### Enterprise AI Knowledge Platform
- **Advanced RAG**: Retrieves specialized manuals, safety standards, and historical documentation for targeted troubleshooting (e.g., Sulzer AHLSTAR or Framo SD125 safety limits).
- **Strict Guardrails**: 
  - **Input Guardrails**: Evaluates incoming queries for safety-bypass attempts and force-overrides, blocking malicious operational commands before they hit any retrieval nodes.
  - **Output Guardrails**: Intercepts the final synthesis. If an ATEX gas hazard is active, it strictly enforces that the LLM's response contains a mandatory `SAFETY ALERT` warning.
- **LLMOps & Telemetry**: Every tool and LLM invocation logs token usage (`tiktoken`), estimated API costs, execution latency, and triage utilization rates to a local audit table. View metrics using the `audit_report.py` CLI.

### Autonomous Multi-Agent AI Platform
- **CEMG Integration**: Integrates the Causal Experience Memory Graph (CEMG). The system uses memory blocks to "peek" the signature status of MCP tools, avoiding infinite retry loops on failing APIs by putting them in `ACTIVE_FAILURE` probation.
- **Persistent Human-In-The-Loop (HITL)**: Swapped out the local `MemorySaver` checkpointer for an `AsyncSqliteSaver` wrapped in a custom `LazyCompiledGraph`. Paused states for Work Order creation are now securely persisted to disk, surviving server/process restarts.
- **Long-Term Memory Profile Consolidation**: As the crew interacts with the chatbot, their profile is dynamically updated to track which machinery and vessel classes they gain experience with over time.

## Architecture

```text
TriageRouter -> ResolveEquipment -> ATEXHazardCheck (always runs)
                                          |
                    -------------------------------------------------
                    |              |              |                |
              LogbookExtraction  Onboarding    Checklist      FanOutOrchestrator
              (deterministic,    Compatibility  Agent         (gated: telemetry,
               not gated)        Agent                        compliance, history,
                    |              |              |            weather, maps)
                    |              |              |                |
                    |              |              |          SynthesisAgent
                    |              |              |                |
                    |              |              |          ActionAgent
                    |              |              |          (HITL checkpointer pause)
                    -------------------------------------------------
                                          |
                                     AuditNode -> END
```

## Files

```
schema.sql          Full DB schema including RAG documents, tool_call_audit token tracking,
                    and chat history message tracking.
db.py               Async data-access layer for RAG, profile consolidation, and SQLite.
graph.py            The LangGraph orchestrator — contains Input/Output Guardrails, LLMOps logic,
                    CEMG execution wrappers, and the LazyCompiledGraph SQLite checkpointer.
tests/seed.py       Seeds a fresh SQLite DB with test machinery, ATEX limits, RAG docs, and profiles.
tests/test_harness.py Runs interaction scenarios simulating the frontend APIs.
tests/run_evals.py  Evaluation suite to assert guardrail blocking, RAG precision, and CEMG resilience.
tests/audit_report.py Aggregates LLMOps token metrics, cost estimators, and latency reports.
```

## Setup & Running Locally

1. Create a virtual environment and install dependencies:
```bash
python -m venv venv
.\venv\Scripts\activate  # On Windows
pip install -r requirements.txt
pip install -e ../cemg  # Install the sibling CEMG package for memory features
```

2. Generate the database and verify the graph execution:
```bash
python tests/seed.py
python tests/test_harness.py
```

3. View LLMOps metrics:
```bash
python tests/audit_report.py
```

*Note: The test suites mock only the LLM boundary, so they can run without network access. Everything else: routing, RAG search, ATEX threshold logic, the human-approval pause/resume cycle, CEMG probation, and LLMOps writes is real code.*
