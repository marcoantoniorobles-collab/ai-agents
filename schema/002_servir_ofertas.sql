-- =========================================================
-- Tabla de seguimiento persistente: ofertas SERVIR
-- Vive en la misma base ai_agents (Postgres compartida), en su propia
-- tabla — no se mezcla con el esquema de control de agentes/tareas.
-- =========================================================

CREATE TABLE servir_ofertas (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero_convocatoria TEXT NOT NULL,
    entidad             TEXT NOT NULL,
    titulo              TEXT,
    ubicacion           TEXT,
    vacantes            TEXT,
    remuneracion        TEXT,
    fecha_inicio        TEXT,
    fecha_fin           TEXT,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_by_user     BOOLEAN NOT NULL DEFAULT false,
    removed_by_user_at  TIMESTAMPTZ,

    UNIQUE (numero_convocatoria, entidad)
);

CREATE INDEX idx_servir_ofertas_removed ON servir_ofertas (removed_by_user);
CREATE INDEX idx_servir_ofertas_last_seen ON servir_ofertas (last_seen_at);
