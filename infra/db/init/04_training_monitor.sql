-- =============================================================================
-- Remote Training Monitor (read-only telemetry)
--   적용 순서: 01_extensions -> 02_schema -> 03_trading_schema -> (이 파일)
--
-- 보안 모델
--   * 쓰기: 학습 머신이 service_role 키로만 수행 (service_role 은 RLS 우회).
--           service key 는 학습 머신 .env 에만 둔다. Git/브라우저/Vercel client bundle 금지.
--   * 읽기: 로그인한 사용자 중 vt.admin_users 에 등록된 이메일만 SELECT 가능 (RLS).
--   * anon / 일반 authenticated 사용자는 접근 불가.
-- 이 테이블에는 dataset / checkpoint 파일 / 전체 traceback / 절대경로를 넣지 않는다.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS vt;

-- 대시보드 열람 허용 계정 (서버에서만 관리; 클라이언트 직접 접근 불가)
CREATE TABLE IF NOT EXISTS vt.admin_users (
  email       TEXT PRIMARY KEY,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE vt.admin_users ENABLE ROW LEVEL SECURITY;
-- policy 없음 = authenticated/anon 모두 직접 접근 불가. is_admin() 만 SECURITY DEFINER 로 조회.

CREATE OR REPLACE FUNCTION vt.is_admin()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = vt, public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM vt.admin_users
    WHERE lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;
REVOKE ALL ON FUNCTION vt.is_admin() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION vt.is_admin() TO authenticated;

-- =============
-- Runs (현재 상태 1행 / run)
-- =============
CREATE TABLE IF NOT EXISTS vt.training_runs (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id               TEXT UNIQUE NOT NULL,
  experiment_name      TEXT,
  model_name           TEXT,
  status               TEXT NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED','INTERRUPTED','CANCELLED')),
  hostname             TEXT,
  gpu_name             TEXT,
  started_at           TIMESTAMPTZ,
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at          TIMESTAMPTZ,
  current_epoch        INTEGER,
  total_epochs         INTEGER,
  current_step         BIGINT,
  total_steps          BIGINT,
  progress             DOUBLE PRECISION,
  train_loss           DOUBLE PRECISION,
  val_loss             DOUBLE PRECISION,
  accuracy             DOUBLE PRECISION,
  macro_f1             DOUBLE PRECISION,
  mae                  DOUBLE PRECISION,
  rmse                 DOUBLE PRECISION,
  spearman_ic          DOUBLE PRECISION,
  learning_rate        DOUBLE PRECISION,
  gpu_utilization      DOUBLE PRECISION,
  gpu_memory_used_mb   INTEGER,
  gpu_memory_total_mb  INTEGER,
  elapsed_seconds      BIGINT,
  checkpoint_path      TEXT,          -- 파일명/상대경로만 (절대경로 금지)
  log_tail             TEXT,          -- 최근 10~20줄, sanitize 됨
  error_message        TEXT,          -- sanitize 된 요약만 (traceback 전문 금지)
  git_commit           TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_training_runs_updated ON vt.training_runs(updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_training_runs_status ON vt.training_runs(status, updated_at DESC);

-- =============
-- Metric history (long format; epoch/validation 단위로만 기록 — batch 단위 금지)
-- =============
CREATE TABLE IF NOT EXISTS vt.training_metrics (
  id            BIGSERIAL PRIMARY KEY,
  run_id        TEXT NOT NULL REFERENCES vt.training_runs(run_id) ON DELETE CASCADE,
  "timestamp"   TIMESTAMPTZ NOT NULL DEFAULT now(),
  epoch         INTEGER,
  step          BIGINT,
  split         TEXT NOT NULL CHECK (split IN ('train','val','test')),
  metric_name   TEXT NOT NULL,
  metric_value  DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_training_metrics_run_ts ON vt.training_metrics(run_id, "timestamp");
CREATE INDEX IF NOT EXISTS ix_training_metrics_run_name ON vt.training_metrics(run_id, metric_name, step);

-- =============
-- RLS
-- =============
ALTER TABLE vt.training_runs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE vt.training_metrics ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS training_runs_admin_select ON vt.training_runs;
CREATE POLICY training_runs_admin_select ON vt.training_runs
  FOR SELECT TO authenticated USING (vt.is_admin());

DROP POLICY IF EXISTS training_metrics_admin_select ON vt.training_metrics;
CREATE POLICY training_metrics_admin_select ON vt.training_metrics
  FOR SELECT TO authenticated USING (vt.is_admin());

-- INSERT/UPDATE/DELETE policy 는 의도적으로 만들지 않는다: service_role(학습 머신)만 쓸 수 있다.
REVOKE ALL ON vt.training_runs, vt.training_metrics, vt.admin_users FROM anon;
GRANT SELECT ON vt.training_runs, vt.training_metrics TO authenticated;
GRANT USAGE ON SCHEMA vt TO authenticated;

-- 최초 1회: 본인 이메일 등록
--   INSERT INTO vt.admin_users(email) VALUES ('<your-email>');
