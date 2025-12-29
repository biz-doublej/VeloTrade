# VeloTrade 크롤링·벡터화·LLaMA 연동 개발 기획서

## 0. 문서 목적

VeloTrade는 미국 주식 시장의 **이벤트(뉴스/발언/공시/실적/거시)**를 정기적으로 수집하고, 모든 수집 데이터를 **벡터 임베딩으로 축소 저장**하여, 사용자의 질문에 대해 **(1) 신선한 근거를 확보(온디맨드 크롤링) + (2) 벡터 검색(RAG) + (3) 예측 지표(50.1% 목표) + (4) 설명/근거 제시**까지 일관된 파이프라인으로 제공하는 시스템을 구축한다.

---

## 1. 목표

### 1.1 핵심 목표

1. **정기 크롤링**: 특정 주기마다 Fast/Slow Lane으로 자동 수집
2. **질문 기반 온디맨드 크롤링**: 사용자가 종목/카테고리를 질문하면 TTL 검사 후 필요한 범위만 추가 수집
3. **유명 종목 우선 유니버스 운영**: 운영 안정성을 위해 상위 종목/ETF로 시작
4. **유명인 발언 이벤트화**: Trump/Musk/Powell 등 발언을 “이벤트”로 구조화하여 시장/종목에 연결
5. **전량 벡터화(용량 축소)**: 모든 크롤링 결과를 임베딩으로 저장(원문은 최소/압축 형태로만 보관)

### 1.2 성공 지표 (MVP 기준)

* 수집 안정성: 도메인 차단률 < 1%/day, 재시도 성공률 > 95%
* 검색 품질: 질문에 대한 근거 문서 Top-5 적중(수동 평가) 80% 이상
* 응답 시간: 온디맨드 크롤링 없는 경우 2~5초 내 답변, 있는 경우 15~60초 내 답변(소스에 따라)
* 예측 지표: “상승/하락 확률” 출력 가능(목표 정확도 50.1%로 운영), **근거 기반 설명** 포함

---

## 2. 범위 정의

### 2.1 포함

* 크롤링 대상 카테고리:

  * **Celeb/Influencer**: Trump, Elon Musk, Fed Chair (Powell)
  * **Top Stocks/ETFs**: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA 등
  * **Macro**: FOMC, CPI/PCE, NFP 등
  * **Earnings/Press**: 실적 발표/프레스 릴리즈/가이던스
* 저장: PostgreSQL + pgvector에 문서/청크/임베딩/메타/로그 저장
* 검색: Vector similarity + 필터(티커/카테고리/기간/소스)
* LLaMA 연동:

  * 요약/이벤트 추출/질문 이해/근거 기반 답변 생성
  * QLoRA는 “설명/라벨링 품질 향상” 목적

### 2.2 제외(초기)

* 모든 상장종목 전체 커버(초기엔 유명 종목 유니버스 고정 후 확장)
* 초단타 트레이딩 실행 자동화(IBKR 주문까지 자동은 이후 옵션)
* 멀티모달(이미지/영상) 처리

---

## 3. 시스템 아키텍처

### 3.1 핵심 설계: 2-Lane + 2-Trigger

* **Lane**

  * Fast Lane: 속보/발언/헤드라인 중심(짧게 자주 “변경 확인”)
  * Slow Lane: 실적/거시/리포트 중심(분~시간 단위)
* **Trigger**

  * Scheduler Trigger: 특정 시간마다 자동 수집
  * On-Demand Trigger: 사용자 질문 시 TTL 검사 후 필요한 범위만 큐에 투입

### 3.2 데이터 플로우

1. 키워드/쿼리(templates → compiled) 기반 수집 대상 생성
2. Fetcher(httpx/Playwright)로 페이지/피드 요청
3. Parser로 본문 텍스트/메타 추출
4. Normalize + Dedupe(해시/유사도)
5. Entity Linking(티커/인물/토픽 연결)
6. Chunking(300~800 tokens)
7. Embedding 생성
8. pgvector upsert
9. 사용자 질문 → Query Router → Vector Search → LLaMA 답변 + 예측 지표 출력

---

## 4. 데이터베이스 선정 (1개 확정)

### ✅ 선택: PostgreSQL + pgvector

**선정 이유**

* 관계형(메타/로그/작업큐) + 벡터(임베딩 검색) 동시 처리 가능
* 운영·백업·마이그레이션 안정적
* 필터 기반 검색(티커/기간/소스)과 벡터 검색 결합이 쉬움
* 로컬 개발 → 향후 서버 확장에 그대로 가져갈 수 있음

---

## 5. 저장 모델 (DB 스키마 설계)

### 5.1 주요 테이블

#### (1) sources

* id, name, domain, lane(fast/slow), rate_limit_rps, supports_etag, enabled

#### (2) documents (원문 최소/압축 저장)

* doc_id(UUID)
* source_id
* url, url_hash
* title
* published_at, fetched_at
* lang
* raw_text_min (제목+핵심문장 3~5개)
* raw_text_gzip (선택: 본문 압축 저장)
* content_hash (중복 제거)
* entity_tags (jsonb: tickers, people, topics)

#### (3) chunks (벡터화 단위)

* chunk_id(UUID)
* doc_id(FK)
* chunk_index
* chunk_text (짧게, 300~800 tokens)
* embedding vector(예: 768 dims)
* tokens_count
* metadata jsonb (ticker, topic, lane, ttl, …)

#### (4) crawl_jobs / crawl_runs

* 어떤 job이 언제 무엇을 돌았는지 기록(감사/재현)
* status, error, retry_count, duration_ms, items_fetched

#### (5) query_logs (사용자 질문 로그)

* question, parsed_intent, selected_tickers/categories
* used_docs/chunks
* answer_text
* model_version, latency

### 5.2 “전량 벡터화” 정책

* **모든 document → chunking → embedding 생성 → chunks 테이블 upsert**
* 원문은 디버깅/법적 근거/재처리를 위해 **최소 텍스트**만 저장(또는 gzip 압축)

---

## 6. 크롤러 설계

### 6.1 크롤링 엔진 구성요소

* Scheduler: APScheduler(로컬) 또는 Windows 작업 스케줄러 + runner
* Queue/RateLimiter: 도메인 단위 레이트리밋 + 백오프
* Fetcher:

  * 기본: httpx(ETag/If-Modified-Since 조건부 요청 지원)
  * 필요 시: Playwright(동적 렌더링 소스)
* Parser: readability-lxml / trafilatura 등 본문 추출기
* Dedupe:

  * url_hash(중복 URL 방지)
  * content_hash(같은 기사 중복 방지)
  * simhash(유사 기사 억제, 선택)
* Entity Linking:

  * 룰 기반(티커 사전/유명인 매핑)
  * * LLaMA로 보강(토픽 분류, 연결 보정)

### 6.2 주기 설계 (권장)

* Fast Lane

  * 30초~2분: “새 글 여부 확인” 중심(조건부 요청)
* Slow Lane

  * 15~60분: 거시/실적/공시/리포트

> “1초마다 크롤링”은 **요청을 1초마다 보내는 것**이 아니라,
> **큐/업데이트 상태를 1초마다 확인**하고 요청은 조건부로 최소화하는 형태로 구현.

### 6.3 기본 유니버스(유명 종목)

* ETFs: SPY, QQQ, DIA, IWM
* Mega-cap: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA
* 추가 대표: JPM, XOM, CVX, AMD, AVGO, TSM, INTC

universe.yaml로 관리하고, 사용자 요청 시 동적으로 확장.

### 6.4 유명인 발언 이벤트 처리

* 인물(Trump/Musk/Powell) + 발언 텍스트 + 시간 + 소스 저장
* entity_linker가 “영향 티커/섹터”를 연결(룰 + LLaMA 분류)
* 예:

  * Musk → TSLA 기본 연결
  * Trump + tariff → 제조/반도체/중국노출 가중
  * Powell → 전시장 + 금리 민감 섹터

---

## 7. 벡터화(임베딩) 설계

### 7.1 임베딩 모델 선택(로컬 친화)

* 추천: **bge-small-en / e5-base** 계열

  * 이유: 로컬에서 빠르고, 검색 품질 안정적
* chunk 길이: 300~800 tokens
* 저장: pgvector

### 7.2 벡터 검색 전략

* 1차: 벡터 유사도 Top-K(예: 20)
* 2차: 메타 필터(ticker/category/lane/시간)로 재정렬
* 3차: 최근성 가중(Recency boost)

---

## 8. LLaMA 연동: 학습 / 서치 / 추론 / 예측

### 8.1 역할 분리(중요)

* **LLaMA(LLM)**:

  * 질문 이해(티커/카테고리/의도 분류)
  * 문서 요약/근거 정리
  * 설명 생성(왜 이런 확률이 나왔는지)
* **예측 엔진(RS/Rule/통계 모델)**:

  * “상승/하락 확률” 산출(목표 50.1% 운영)
  * LLM이 직접 가격 예측을 ‘사실처럼’ 말하게 두지 않음(리스크 감소)

### 8.2 QLoRA 학습 범위(현실적)

RTX 3070 기준에서 LLaMA 3.1 8B QLoRA로 할 만한 건:

* “문서 → 핵심 요약/토픽 라벨링”
* “근거 기반 답변 포맷 준수(JSON/정형 출력)”
* “유명인 발언 → 토픽/영향 섹터 분류 품질 향상”

즉, 가격 예측 그 자체를 학습하기보다는 **리서치/설명 파이프라인 품질**을 올린다.

### 8.3 검색(RAG) 결합

* 사용자 질문 → 라우팅(티커/카테고리/기간)
* Vector DB에서 관련 chunks 검색
* LLaMA에 “근거 chunks + 질문 + 출력 포맷”으로 추론
* 답변에 근거 3~5개를 포함(출처/시간/요약)

### 8.4 예측(확률) 출력 설계

* 출력 예시:

  * Direction Probability: Up 52% / Down 48%
  * Confidence: Low/Med/High
  * Drivers: 3개(발언/거시/실적)
  * Evidence: 근거 문서 3~5개
  * Risk Notes: 변동성/이벤트 리스크

---

## 9. On-Demand 크롤링 규칙 (TTL 기반)

### 9.1 TTL 정책

* Celeb/Breaking: 5~15분
* Earnings/Press: 6~24시간
* Macro: 발표 전후 1~6시간(이벤트 캘린더 기반 확장 가능)

### 9.2 요청 흐름

1. 질문 파싱(티커/카테고리/인물)
2. last_updated 조회
3. TTL 초과 → 해당 항목만 crawl_jobs에 enqueue
4. 새 문서 도착 시 embedding upsert
5. 검색 + 답변 생성

---

## 10. 개발 순서 (MVP → 확장)

### Phase 1: “수집-저장-검색” MVP

1. keywords/templates/compiled 정리
2. Slow Lane 크롤러 구현(기사/리포트 파서 안정화)
3. Dedupe + 최소 원문 저장
4. Embedding 생성 + pgvector upsert
5. Vector Search API

**산출물**

* pgvector 인덱스 구축
* “질문 → 관련 문서 Top-K” 동작 확인

### Phase 2: On-Demand + TTL

1. 질문 파서(티커/카테고리 추출)
2. TTL 검사 + on-demand enqueue
3. “질문 시 자동 갱신 후 답변” 구현

### Phase 3: Fast Lane + 유명인 이벤트

1. 유명인 발언 소스 수집(헤드라인/소셜/인터뷰)
2. 이벤트 스키마 저장 + 티커 연결(룰 기반)
3. RAG 답변에 “발언 기반 근거” 반영

### Phase 4: LLaMA 정형 출력 + QLoRA

1. LLaMA 출력 포맷 고정(JSON/템플릿)
2. QLoRA로 요약/라벨링/포맷 준수 강화
3. 회귀 테스트(같은 질문에 일관된 답)

### Phase 5: 예측 엔진 고도화(선택)

1. RS/룰+간단 ML(가격/변동성 지표) 결합
2. 확률 출력 안정화(목표 50.1% 운영)

---

## 11. 운영/모니터링

### 11.1 로깅

* crawl_runs: 수집 성공/실패, 도메인별 차단률
* query_logs: 질의별 검색 결과, 응답 시간, 사용된 근거

### 11.2 품질 관리

* 중복률/노이즈율 모니터링
* 출처 신뢰도 스코어(소스별 가중치)
* “근거 없는 답변” 방지: 근거 chunks가 없으면 ‘자료 부족’로 응답

### 11.3 법/리스크 문구

* 투자 자문이 아니라 정보 제공임을 명시(웹 UI/응답에 포함)

---

## 12. 프로젝트 폴더 구조(권장)

```
VeloTrade/
├─ keywords/                 # 키워드/템플릿/compiled
├─ crawler/
│  ├─ config/                # sources.yaml, universe.yaml, runtime.yaml
│  ├─ jobs/                  # scheduler, fast/slow, on_demand
│  ├─ pipeline/              # fetch/parse/dedupe/link/embed/store
│  └─ api/                   # 질문 라우팅/크롤링 트리거
├─ vectorstore/              # pgvector 접속/쿼리 레이어
├─ training/                 # QLoRA/평가/실험
└─ app/                      # 웹/API 서버(예: FastAPI)
```

---

## 13. 결정 사항 요약

* DB: **PostgreSQL + pgvector** (확정)
* 모델: **LLaMA 3.1 8B Instruct(로컬) + QLoRA**
* 저장: 전량 임베딩 + 최소 원문(압축)
* 크롤링: 2-Lane(FAST/SLOW) + 2-Trigger(Scheduled/OnDemand)
* 답변: RAG(근거 제시) + 예측 지표(50.1% 목표)

---

크롤러 만드는 게 아니라, **시장 리서치 엔진(벡터 기반)** 만드는 것.
