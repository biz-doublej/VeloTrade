-- =============
-- Sources
-- =============
CREATE TABLE IF NOT EXISTS vt.sources (
  source_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name             TEXT NOT NULL,
  domain           TEXT NOT NULL,
  lane             TEXT NOT NULL CHECK (lane IN ('fast', 'slow')),
  rate_limit_rps   NUMERIC(6,2) NOT NULL DEFAULT 0.50,
  supports_etag    BOOLEAN NOT NULL DEFAULT FALSE,
  enabled          BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_sources_domain_name
ON vt.sources(domain, name);

-- =============
-- Documents
-- =============
CREATE TABLE IF NOT EXISTS vt.documents (
  doc_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id        UUID REFERENCES vt.sources(source_id) ON DELETE SET NULL,

  url              TEXT NOT NULL,
  url_hash         TEXT NOT NULL,
  title            TEXT,
  published_at     TIMESTAMPTZ,
  fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  lang             TEXT NOT NULL DEFAULT 'en',

  raw_text_min     TEXT,
  raw_text_gzip    BYTEA,

  content_hash     TEXT NOT NULL,
  entity_tags      JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_url_hash
ON vt.documents(url_hash);

CREATE INDEX IF NOT EXISTS ix_documents_published_at
ON vt.documents(published_at);

-- =============
-- Chunks (vector)
-- embedding 차원 768 고정 (사용 임베딩 모델 차원과 맞춰야 함)
-- =============
CREATE TABLE IF NOT EXISTS vt.chunks (
  chunk_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id           UUID NOT NULL REFERENCES vt.documents(doc_id) ON DELETE CASCADE,
  chunk_index      INT NOT NULL,

  chunk_text       TEXT NOT NULL,
  tokens_count     INT,
  embedding        vector(768),

  metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_chunks_doc_idx
ON vt.chunks(doc_id, chunk_index);

CREATE INDEX IF NOT EXISTS ix_chunks_metadata_gin
ON vt.chunks USING GIN (metadata);

-- ivfflat 인덱스: 데이터가 쌓여야 효율적.
-- 처음부터 만들면 느릴 수도 있음. 일단 켜두고 나중에 lists 조정해도 됨.
CREATE INDEX IF NOT EXISTS ix_chunks_embedding_cosine
ON vt.chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- =============
-- Crawl Jobs / Runs
-- =============
CREATE TABLE IF NOT EXISTS vt.crawl_jobs (
  job_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type         TEXT NOT NULL CHECK (job_type IN ('scheduled', 'on_demand')),
  lane             TEXT NOT NULL CHECK (lane IN ('fast', 'slow')),
  target           JSONB NOT NULL DEFAULT '{}'::jsonb,
  status           TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','success','failed')),
  priority         INT NOT NULL DEFAULT 100,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at       TIMESTAMPTZ,
  finished_at      TIMESTAMPTZ,
  error_message    TEXT
);

CREATE INDEX IF NOT EXISTS ix_crawl_jobs_status_priority
ON vt.crawl_jobs(status, priority, created_at);

CREATE TABLE IF NOT EXISTS vt.crawl_runs (
  run_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id           UUID REFERENCES vt.crawl_jobs(job_id) ON DELETE SET NULL,
  source_id        UUID REFERENCES vt.sources(source_id) ON DELETE SET NULL,

  fetched_count    INT NOT NULL DEFAULT 0,
  stored_docs      INT NOT NULL DEFAULT 0,
  stored_chunks    INT NOT NULL DEFAULT 0,

  duration_ms      INT,
  status           TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success','failed')),
  error_message    TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============
-- Query Logs
-- =============
CREATE TABLE IF NOT EXISTS vt.query_logs (
  qlog_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  question         TEXT NOT NULL,
  parsed_intent    JSONB NOT NULL DEFAULT '{}'::jsonb,

  used_doc_ids     UUID[],
  used_chunk_ids   UUID[],

  answer_text      TEXT,
  model_version    TEXT,
  latency_ms       INT,

  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
