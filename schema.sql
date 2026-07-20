-- ============================================================
-- Vessel Engineering Copilot — Schema v4
-- Adds: equipment-centric model, logbook extraction, crew
-- compatibility profiles, checklists. Prior tables (tenants,
-- vessels, threads, messages, work_orders, tool_call_audit)
-- retained from v3 with FK integrity fixes already applied.
-- ============================================================

CREATE TABLE tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    fleet_operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vessels (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    imo_number INTEGER UNIQUE NOT NULL,
    vessel_type TEXT NOT NULL,          -- 'oil_tanker','lng_carrier','bulk_carrier', etc.
    vessel_class TEXT NOT NULL,         -- e.g. "Suezmax", "Aframax" — used for compatibility matching
    build_date DATE NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT
);

CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    vessel_id TEXT NOT NULL,
    engineer_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    role TEXT CHECK(role IN ('user', 'assistant', 'system')) NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    token_count INTEGER,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

-- ============================================================
-- Equipment-centric core. This is what makes onboarding,
-- diagnostics, and logs persist at the machine level instead
-- of the conversation level.
-- ============================================================

CREATE TABLE equipment (
    id TEXT PRIMARY KEY,
    vessel_id TEXT NOT NULL,
    name TEXT NOT NULL,
    system_category TEXT NOT NULL,          -- 'propulsion','cargo','electrical','ballast', etc.
    criticality_tier TEXT CHECK(criticality_tier IN ('critical','sub_critical','routine')) NOT NULL,
    is_atex_zone INTEGER CHECK(is_atex_zone IN (0,1)) DEFAULT 0,
    atex_zone_class TEXT CHECK(atex_zone_class IN ('Zone 0','Zone 1','Zone 2') OR atex_zone_class IS NULL),
    manufacturer TEXT,
    model TEXT,
    manual_doc_ref TEXT,                    -- pointer into the rules/manual MCP's doc index
    FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE RESTRICT
);
CREATE INDEX idx_equipment_vessel ON equipment(vessel_id);
CREATE INDEX idx_equipment_atex ON equipment(is_atex_zone, atex_zone_class);

CREATE TABLE equipment_logs (
    id TEXT PRIMARY KEY,
    equipment_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    engineer_id TEXT NOT NULL,
    raw_entry TEXT NOT NULL,                -- crew's own sentence, verbatim, never altered
    structured_summary TEXT NOT NULL,       -- JSON: {symptom, action_taken, outcome}
    log_type TEXT CHECK(log_type IN ('maintenance','diagnostic','checklist','incident')) NOT NULL,
    extraction_confidence REAL,             -- flags low-confidence extractions for human review
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE RESTRICT,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE RESTRICT
);
CREATE INDEX idx_logs_equipment ON equipment_logs(equipment_id, timestamp);

-- Crew compatibility: what an engineer already knows, vs. what
-- a new vessel actually has. Powers the onboarding delta-check.
CREATE TABLE crew_profiles (
    id TEXT PRIMARY KEY,
    engineer_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    known_vessel_classes TEXT NOT NULL,     -- JSON list, e.g. ["Suezmax","VLCC"]
    known_equipment_models TEXT,            -- JSON list of manufacturer/model pairs
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT
);
CREATE INDEX idx_crew_profiles_engineer ON crew_profiles(engineer_id);

CREATE TABLE checklist_templates (
    id TEXT PRIMARY KEY,
    equipment_id TEXT,                      -- NULL = vessel-wide, not equipment-specific
    vessel_class TEXT,                      -- reusable across sister ships of the same class
    title TEXT NOT NULL,
    items_json TEXT NOT NULL,               -- ordered list of checklist item strings
    FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE RESTRICT
);

CREATE TABLE checklist_completions (
    id TEXT PRIMARY KEY,
    checklist_template_id TEXT NOT NULL,
    vessel_id TEXT NOT NULL,
    engineer_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    items_completed_json TEXT NOT NULL,     -- {item_index: bool}
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (checklist_template_id) REFERENCES checklist_templates(id) ON DELETE RESTRICT,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE RESTRICT
);

-- ============================================================
-- Safety-critical: ATEX hazard events. Deliberately separate
-- from tool_call_audit — this table must be queryable on its
-- own for safety review, independent of general agent telemetry.
-- ============================================================

CREATE TABLE atex_hazard_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    vessel_id TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    zone_class TEXT NOT NULL,
    trigger_reading TEXT NOT NULL,          -- JSON snapshot of the telemetry that triggered this
    severity TEXT CHECK(severity IN ('advisory','warning','critical')) NOT NULL,
    crew_acknowledged INTEGER CHECK(crew_acknowledged IN (0,1)) DEFAULT 0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE RESTRICT,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE RESTRICT
);
CREATE INDEX idx_atex_events_vessel ON atex_hazard_events(vessel_id, timestamp);

-- ============================================================
-- Regulatory / audit-critical tables (from v3, unchanged logic:
-- RESTRICT not CASCADE — deleting a thread must never destroy
-- the record of what the AI did or recommended).
-- ============================================================

CREATE TABLE work_orders (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    vessel_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    created_by_agent TEXT NOT NULL,
    justification TEXT NOT NULL,
    status TEXT CHECK(status IN ('pending', 'approved', 'rejected')) DEFAULT 'pending',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT,
    FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE RESTRICT,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE RESTRICT,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE RESTRICT
);
CREATE INDEX idx_work_orders_thread_turn ON work_orders(thread_id, turn_id);
CREATE INDEX idx_work_orders_equipment ON work_orders(equipment_id);

CREATE TABLE tool_call_audit (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    gate_fired INTEGER CHECK(gate_fired IN (0, 1)) NOT NULL,
    gate_reasoning TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    tool_name TEXT NOT NULL,
    input_payload TEXT NOT NULL,
    output_payload TEXT,
    is_used_by_synthesis INTEGER CHECK(is_used_by_synthesis IN (0, 1)) DEFAULT 0,
    latency_ms INTEGER NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    estimated_cost REAL DEFAULT 0.0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE RESTRICT
);
CREATE INDEX idx_audit_lookup ON tool_call_audit(tenant_id, thread_id, turn_id);
CREATE INDEX idx_audit_efficiency_metric ON tool_call_audit(gate_fired, is_used_by_synthesis);

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    equipment_id TEXT,                      -- NULL = vessel-wide or general safety
    vessel_class TEXT,                      -- e.g. "Aframax"
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    section_name TEXT,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE RESTRICT
);
CREATE INDEX idx_documents_lookup ON documents(equipment_id, vessel_class);

CREATE INDEX idx_vessels_tenant ON vessels(tenant_id);
CREATE INDEX idx_threads_tenant ON threads(tenant_id);
CREATE INDEX idx_threads_vessel ON threads(vessel_id);
CREATE INDEX idx_messages_thread ON messages(thread_id);
