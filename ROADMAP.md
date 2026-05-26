# VeloTrade 14일 MVP 로드맵 (자동매매 통합 버전)

> Baseline 변경 (5/26): "조회·분석"만이던 14일 스코프를 **개인용 자동 추적·알림·리밸런싱·매매** 까지 확장.
> Day 1-14 plan 은 [day-1-5-7-dynamic-dewdrop.md](~/.claude/plans/day-1-5-7-dynamic-dewdrop.md) → 본 문서로 승계.

## Must (14일 안에 반드시)

- [x] **Day 1** Next.js 14 + Supabase 셋업, "Hello VeloTrade" 배포
- [x] **Day 1** `trading/` Python 모듈 골격 (어댑터·전략·리스크·러너·CLI)
- [x] **Day 2** Alpaca paper 실가동 (시세·계좌·주문 end-to-end)
- [x] **Day 2** Supabase 스키마 + Python DB 기록 레이어 + 시드 데이터 (3 계좌, 17 종목)
- [x] **Day 2** Alpaca WebSocket 시세 스트림 (IEX feed)
- [x] **Day 3** Binance testnet WebSocket + 실주문 (BTCUSDT 매수 즉시 체결)
- [x] **Day 3** Upbit WebSocket 시세 (public_only) + PaperExchange 시뮬레이션
- [x] **Day 3** 멀티 거래소 동시 운영 (`run-all` CLI, asyncio.gather)
- [x] **Day 4** 자체 백테스트 엔진 + RSI/MA cross grid search (32건 DB 저장)
- [x] **Day 4** 전략 파라미터 튜닝 — Best RSI(14, 30/75) Sharpe 1.10 return +102.96%
- [x] **Day 5** RiskManager 통합 테스트 13건 (위반 시나리오 100% 차단)
- [x] **Day 5** 백테스트 fetch 정확도 — start/end 파라미터 + warmup 단축
- [x] **Day 5** 종목 확장 백테스트 24종 — sweet spot 도출 (RSI(21, 30/75))
- [x] **Day 6** Web 대시보드 1차: Positions/Orders/Signals/Backtests 페이지
  + Supabase 서버 클라이언트 (vt 스키마 + service_role)
  + 자체 UI 컴포넌트 (data-table/badge/page-header, Tailwind 3 호환)
- [x] **Day 7** Web 대시보드 2차: Watchlist + Strategies CRUD (Server Actions)
  + 봇 watchlist polling reload — 30s 마다 자동 반영
- [x] **Day 8** Supabase Auth (Magic Link) + middleware 가드
  + ALLOWED_EMAIL env 화이트리스트로 본인 1계정만 허용
  + /login, /auth/callback, /auth/logout, sidebar 사용자 정보
- [x] **Day 9** 알림 (Discord rich embed + Slack mrkdwn + stdout)
  + 429 자동 재시도 + URL 마스킹 로깅 + 안전 truncate
  + /dashboard/alerts 페이지 — 최근 100건 + webhook 설정 안내
- [ ] **Day 11** LLM 시그널 ↔ VeloTrade RAG 연동 (DART/네이버 공시·뉴스 이벤트 → LLM → 시그널)
- [ ] **Day 12** 리밸런싱: 목표 비중 vs 현재 비중 diff → 자동 주문
- [ ] **Day 13** 백테스트 시각화 (equity curve, drawdown) + 멀티 거래소 통합 테스트
- [ ] **Day 14** Paper trading 1-2일 실가동 + 문서·운영 매뉴얼

## Drop (14일 안엔 안 함)

- ❌ LLaMA 3.1 8B 자체 호스팅 + QLoRA → OpenAI / Gemini API
- ❌ Fast Lane 30초 속보 크롤링 → 정기 + 이벤트 기반
- ❌ 예측 엔진 50.1% 적중률 → 정성적 LLM 답변
- ❌ Playwright 동적 크롤링 → 정적 fetch + RSS
- ❌ 모바일 앱 → 반응형 웹
- ❌ 다국어 (영어 UI) → 한국어
- ❌ 결제·구독 → 본인용 무료
- ❌ 다중 사용자 → 본인 1계정만
- ❌ 그리드·DCA 전략 (RSI/MA/LLM 만 — 추후 추가)
- ❌ 옵션/선물/마진 → spot only

## 안전장치 (전 기간 강제)

1. **paper 가 기본**. CLI `--mode live` + `--i-know-this-is-live` 둘 다 명시해야 실거래.
2. **dry-run** 으로 며칠 검증 후 paper, paper 며칠 검증 후 live.
3. 거래소 API 키는 **출금 권한 OFF + IP 화이트리스트** 필수.
4. RiskConfig: 단일 거래 5%, 종목당 20%, 일일 손실 2% (이하 한도는 .env 로 변경).
5. 모든 주문은 `vt.orders` 기록 → Web 에서 감사 가능.
6. 손실은 본인 책임 — Claude 가 작성한 코드의 정확성을 보장하지 않는다.

## 모듈 책임 분리

| 모듈 | 책임 | 언어 |
|------|------|------|
| `web/` | 대시보드, 인증, 사용자 입력, RAG 답변 표시 | Next.js + TS |
| `trading/` | 어댑터, 전략, 리스크, 봇 러너, 백테스트 | Python 3.11+ |
| `crawler/` (보류) | Day 11 이후, 이벤트 → trading 으로 전달 | Python |
| `infra/db/` | Supabase 스키마 원본 (SQL) | SQL |
| Supabase | 공유 상태 (positions, orders, signals, alerts, query_logs) | Postgres + pgvector |

## 첫 실거래 진입 조건 (Day 14)

- [ ] Paper 모드에서 3일 이상 무사고 가동
- [ ] 백테스트 Sharpe > 0, max drawdown < 15%
- [ ] Risk manager 가 의도적 위반 시그널 100% 차단 확인
- [ ] 알림 채널 (Discord 또는 Slack) 정상 작동
- [ ] DB 기록 일관성 (시그널 → 주문 → 포지션) 검증
