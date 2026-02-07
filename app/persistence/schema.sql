-- ============================================================================
-- Runs
-- ============================================================================
CREATE TABLE IF NOT EXISTS runs (
  run_id       TEXT PRIMARY KEY,
  status       TEXT NOT NULL DEFAULT 'queued',
  request_json JSONB NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at  TIMESTAMPTZ NULL,
  error        TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_created_at  ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_finished_at ON runs(finished_at);
CREATE INDEX IF NOT EXISTS idx_runs_status      ON runs(status);

-- ============================================================================
-- Methods registered per run
-- ============================================================================
CREATE TABLE IF NOT EXISTS methods (
  run_id       TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  method_id    TEXT NOT NULL,
  name         TEXT NOT NULL,
  label        TEXT,
  params_json  JSONB,
  status       TEXT NOT NULL DEFAULT 'queued',
  metrics_json JSONB,
  runtime_sec  DOUBLE PRECISION,
  PRIMARY KEY (run_id, method_id)
);

CREATE INDEX IF NOT EXISTS idx_methods_run_id ON methods(run_id);

-- ============================================================================
-- Events (SSE streaming)
-- IMPORTANT: payload_json must match Python persistence layer
-- ============================================================================
CREATE TABLE IF NOT EXISTS events (
  id           BIGSERIAL PRIMARY KEY,
  run_id       TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  type         TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  ts           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_run_id     ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_run_id_id  ON events(run_id, id);
CREATE INDEX IF NOT EXISTS idx_events_type       ON events(type);

-- ============================================================================
-- Points (time-series data)
-- CRITICAL: UNIQUE index required for ON CONFLICT in Python
-- ============================================================================
CREATE TABLE IF NOT EXISTS points (
  id        BIGSERIAL PRIMARY KEY,
  run_id    TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  method_id TEXT NOT NULL,
  step      INTEGER NOT NULL,
  t         DOUBLE PRECISION,
  error_b   DOUBLE PRECISION,
  error_a   DOUBLE PRECISION,
  ts        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_points_run_id     ON points(run_id);
CREATE INDEX IF NOT EXISTS idx_points_run_method ON points(run_id, method_id);

-- 🔥 ESTA LINEA ARREGLA TU ERROR ACTUAL
CREATE UNIQUE INDEX IF NOT EXISTS uq_points_run_method_step
ON points(run_id, method_id, step);

-- ============================================================================
-- Cleanup helper
-- Prefer finished_at if present; fallback to created_at
-- ============================================================================
