-- =============================================================================
-- 자동매매 스키마 (Day 1 추가 — VeloTrade trading 모듈 연동)
-- =============================================================================
-- Supabase 적용 순서:
--   1) 01_extensions.sql (pgcrypto, vector)
--   2) CREATE SCHEMA IF NOT EXISTS vt;
--   3) 02_schema.sql (기본 6개 테이블)
--   4) 03_trading_schema.sql (이 파일)
-- =============================================================================

-- =============
-- 거래소 계좌
-- =============
CREATE TABLE IF NOT EXISTS vt.exchange_accounts (
  account_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exchange       TEXT NOT NULL CHECK (exchange IN ('alpaca','binance','upbit')),
  account_type   TEXT NOT NULL CHECK (account_type IN ('paper','live')),
  label          TEXT NOT NULL,
  -- API 키는 본 DB 가 아니라 .env / 외부 secret 에 보관. 여기엔 참조 키만.
  api_key_ref    TEXT,
  enabled        BOOLEAN NOT NULL DEFAULT TRUE,
  base_currency  TEXT NOT NULL,            -- 'USD' | 'USDT' | 'KRW'
  starting_capital NUMERIC(20,8),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_exchange_accounts_label
ON vt.exchange_accounts(exchange, account_type, label);

-- =============
-- 워치리스트
-- =============
CREATE TABLE IF NOT EXISTS vt.watchlist_items (
  item_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol         TEXT NOT NULL,
  asset_class    TEXT NOT NULL CHECK (asset_class IN ('us_stock','crypto')),
  exchange       TEXT NOT NULL CHECK (exchange IN ('alpaca','binance','upbit')),
  enabled        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_watchlist_symbol
ON vt.watchlist_items(exchange, symbol);

-- =============
-- 전략 인스턴스 (활성화한 전략 + 파라미터)
-- =============
CREATE TABLE IF NOT EXISTS vt.strategy_instances (
  instance_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name           TEXT NOT NULL,
  strategy_type  TEXT NOT NULL CHECK (strategy_type IN ('rsi','ma_cross','grid','llm_signal')),
  params         JSONB NOT NULL DEFAULT '{}'::jsonb,
  account_id     UUID REFERENCES vt.exchange_accounts(account_id) ON DELETE SET NULL,
  symbols        TEXT[] NOT NULL DEFAULT '{}',
  mode           TEXT NOT NULL CHECK (mode IN ('paper','live','dry_run')),
  enabled        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_strategy_instances_account
ON vt.strategy_instances(account_id);

-- =============
-- 시그널 (전략이 발생시킨 신호 로그)
-- =============
CREATE TABLE IF NOT EXISTS vt.signals (
  signal_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instance_id    UUID REFERENCES vt.strategy_instances(instance_id) ON DELETE SET NULL,
  symbol         TEXT NOT NULL,
  side           TEXT NOT NULL CHECK (side IN ('buy','sell','hold')),
  size_pct       NUMERIC(6,4) NOT NULL,
  confidence     NUMERIC(4,3) NOT NULL,
  reasoning      TEXT,
  meta           JSONB NOT NULL DEFAULT '{}'::jsonb,
  rejected_by_risk BOOLEAN NOT NULL DEFAULT FALSE,
  reject_reason  TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_signals_symbol_created
ON vt.signals(symbol, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_signals_instance_created
ON vt.signals(instance_id, created_at DESC);

-- =============
-- 주문 (실제 거래소에 전송된 / 전송 시도된 주문)
-- =============
CREATE TABLE IF NOT EXISTS vt.orders (
  order_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id           UUID REFERENCES vt.signals(signal_id) ON DELETE SET NULL,
  account_id          UUID REFERENCES vt.exchange_accounts(account_id) ON DELETE SET NULL,
  client_order_id     TEXT,                   -- 멱등성 키
  exchange_order_id   TEXT,                   -- 거래소 발급 ID
  symbol              TEXT NOT NULL,
  side                TEXT NOT NULL CHECK (side IN ('buy','sell')),
  order_type          TEXT NOT NULL CHECK (order_type IN ('market','limit')),
  qty                 NUMERIC(20,8) NOT NULL,
  limit_price         NUMERIC(20,8),
  status              TEXT NOT NULL CHECK (status IN
                       ('pending','submitted','partially_filled','filled','cancelled','rejected')),
  filled_qty          NUMERIC(20,8) NOT NULL DEFAULT 0,
  filled_avg_price    NUMERIC(20,8),
  fee                 NUMERIC(20,8),
  raw                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_client_id
ON vt.orders(client_order_id) WHERE client_order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_orders_account_created
ON vt.orders(account_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_orders_status
ON vt.orders(status, created_at DESC);

-- =============
-- 포지션 스냅샷 (봇이 주기적으로 동기화)
-- =============
CREATE TABLE IF NOT EXISTS vt.positions (
  position_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id       UUID NOT NULL REFERENCES vt.exchange_accounts(account_id) ON DELETE CASCADE,
  symbol           TEXT NOT NULL,
  qty              NUMERIC(20,8) NOT NULL,
  avg_entry_price  NUMERIC(20,8) NOT NULL,
  current_price    NUMERIC(20,8),
  unrealized_pnl   NUMERIC(20,8),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_account_symbol
ON vt.positions(account_id, symbol);

-- =============
-- 백테스트 결과
-- =============
CREATE TABLE IF NOT EXISTS vt.backtests (
  backtest_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instance_id      UUID REFERENCES vt.strategy_instances(instance_id) ON DELETE SET NULL,
  strategy_type    TEXT NOT NULL,
  symbols          TEXT[] NOT NULL,
  start_date       DATE NOT NULL,
  end_date         DATE NOT NULL,
  initial_capital  NUMERIC(20,8) NOT NULL,
  final_value      NUMERIC(20,8) NOT NULL,
  total_return_pct NUMERIC(8,4),
  sharpe           NUMERIC(8,4),
  max_drawdown_pct NUMERIC(8,4),
  trade_count      INT NOT NULL DEFAULT 0,
  win_rate_pct     NUMERIC(6,3),
  results          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============
-- 알림 로그
-- =============
CREATE TABLE IF NOT EXISTS vt.alerts (
  alert_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  alert_type     TEXT NOT NULL CHECK (alert_type IN
                  ('price','signal','order','risk_reject','bot_lifecycle','event')),
  level          TEXT NOT NULL CHECK (level IN ('info','warn','error','trade')),
  symbol         TEXT,
  title          TEXT NOT NULL,
  body           TEXT,
  meta           JSONB NOT NULL DEFAULT '{}'::jsonb,
  delivered_via  TEXT[],
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_alerts_created
ON vt.alerts(created_at DESC);

CREATE INDEX IF NOT EXISTS ix_alerts_symbol_created
ON vt.alerts(symbol, created_at DESC);
