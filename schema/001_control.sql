-- =========================================================
-- Esquema de control: agents, tasks, sessions, execution_history
-- Plataforma de agentes IA — ai-agents
-- =========================================================

-- ---------------------------------------------------------
-- agents: inventario de agentes y su estado de heartbeat
-- ---------------------------------------------------------
CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'OFFLINE'
                    CHECK (status IN ('ONLINE', 'OFFLINE', 'BUSY')),
    last_heartbeat  TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- capacidades, versión, host, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agents_status ON agents (status);


-- ---------------------------------------------------------
-- tasks: cola de tareas (Postgres = fuente de verdad)
-- ---------------------------------------------------------
CREATE TABLE tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID REFERENCES agents(id) ON DELETE SET NULL,
    task_type       TEXT NOT NULL,               -- identifica la lógica que debe correr
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'QUEUED', 'RUNNING',
                                       'COMPLETED', 'FAILED', 'DEAD')),
    priority        SMALLINT NOT NULL DEFAULT 0,  -- mayor = más prioridad
    retry_count     SMALLINT NOT NULL DEFAULT 0,
    max_retries     SMALLINT NOT NULL DEFAULT 3,
    error_message   TEXT,
    scheduled_at    TIMESTAMPTZ,                  -- para tareas diferidas/programadas
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Consultas típicas: siguiente tarea a tomar, tareas de un agente, dead-letter
CREATE INDEX idx_tasks_status          ON tasks (status);
CREATE INDEX idx_tasks_agent_id        ON tasks (agent_id);
CREATE INDEX idx_tasks_type            ON tasks (task_type);
CREATE INDEX idx_tasks_payload_gin     ON tasks USING GIN (payload);

-- Patrón de dequeue autoritativo (referencia, no se ejecuta acá):
-- SELECT id FROM tasks
--   WHERE status = 'PENDING' AND (scheduled_at IS NULL OR scheduled_at <= now())
--   ORDER BY priority DESC, created_at ASC
--   LIMIT 1
--   FOR UPDATE SKIP LOCKED;


-- ---------------------------------------------------------
-- sessions: sesiones activas de agentes (ej. storageState de Playwright)
-- ---------------------------------------------------------
CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_type    TEXT NOT NULL,                -- ej. 'browser', 'api_token', etc.
    label           TEXT,                         -- ej. nombre del sitio/servicio
    storage_state   JSONB,                         -- storageState de Playwright u otro dato liviano
    status          TEXT NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE', 'EXPIRED', 'REVOKED')),
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sessions_agent_id ON sessions (agent_id);
CREATE INDEX idx_sessions_status   ON sessions (status);


-- ---------------------------------------------------------
-- execution_history: historial inmutable de ejecuciones (auditoría/observabilidad ligera)
-- ---------------------------------------------------------
CREATE TABLE execution_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_id        UUID REFERENCES agents(id) ON DELETE SET NULL,
    attempt_number  SMALLINT NOT NULL,             -- coincide con retry_count en el momento del intento
    status          TEXT NOT NULL
                    CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    output          JSONB,
    error           TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_execution_history_task_id  ON execution_history (task_id);
CREATE INDEX idx_execution_history_agent_id ON execution_history (agent_id);


-- ---------------------------------------------------------
-- Trigger genérico para mantener updated_at
-- ---------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
