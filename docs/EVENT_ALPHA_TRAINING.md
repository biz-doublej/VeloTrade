# Event Alpha Model v0 — 학습 / 모니터링 가이드

> 이 모델은 **Alpha Estimator** 입니다. 뉴스 → 초과수익 추정치만 출력하며, 주문/수량/거래소 호출 기능이 없습니다.
> 실제 주문은 기존 deterministic `RiskManager` / Portfolio 시스템의 몫이며, 이 모델은 TradingBot 에 연결되어 있지 않습니다.

## 0. 환경 상태 (2026-10-15 기준)

| 항목 | 상태 |
|---|---|
| GPU | RTX 5070 Ti 16GB, CUDA 12.8 (torch 2.11+cu128) — **WORKING** |
| numpy/pandas/sklearn/lightgbm (venv) | 처음에는 App Control 이 `numpy .pyd` 를 차단했으나, 이후 별도 조치 없이 허용됨 (정책 변경은 하지 않음) |
| `python.exe` outbound 네트워크 | **BLOCKED** (`WinError 10013`) — 아래 "Blocking Policy" 참고 |
| 종합 | 학습은 로컬에서 가능, **Python → Supabase 원격 telemetry 는 현재 불가** |

### 현재 막힌 원인
1. **venv `python.exe` outbound `WinError 10013`** — 방화벽/보안 정책으로 보이며 Python 프로세스만 외부 소켓이 차단됨 (PowerShell/uv 는 정상).
   - 결과: HuggingFace/Yahoo 다운로드와 `SupabaseReporter` 전송이 Python 에서 불가능. 데이터/모델 파일은 PowerShell 로 받았다.
2. **numpy `.pyd` App Control 차단** — 최초 시도에서 `numpy.random._generator` 로드가 정책에 의해 차단됨. 이후 같은 venv 에서 정상 import 되었으나(원인 미확인), 정책이 다시 적용되면 재발할 수 있다.

### 현재까지 준비된 것
- `data/event_alpha/raw/financial_news.parquet` (HF `ashraq/financial-news`, 1.85M 헤드라인, 2010–2020-06, **날짜 단위·헤드라인만**)
- `data/event_alpha/raw/prices/*.json` (Yahoo 일봉 190 종목 + SPY/QQQ/^VIX; 델리스트 종목 60개는 누락 → survivorship bias)
- `artifacts/pretrained/event_alpha_encoder/` (FinBERT 가중치/토크나이저, 로컬 경로로만 로드)
- 파이프라인, baseline, GPU 학습, 평가, LocalReporter, SupabaseReporter, `/training` 대시보드, 마이그레이션

### 실행 불가/미검증인 것
- `SupabaseReporter` 의 **실제 네트워크 전송** (단위 테스트는 "실패해도 예외 없음"만 검증)
- Vercel 배포 (`web/.vercel` 프로젝트 연결 없음)
- `/training` 페이지의 **실데이터 렌더링** (Supabase 에 telemetry 가 없어 빈 상태/에러 상태만 빌드 검증)

## 1. 데이터 / 라벨 규약 (leakage 방지)

- 뉴스는 **날짜 단위**라 시각을 모른다 → 의사결정 시점을 "뉴스 날짜 D 종가 이후"로 보수적으로 가정.
- Feature: `D` 이하 마지막 거래일 종가까지의 과거-only 지표 (rolling 은 모두 과거 방향).
- 진입: `D` 이후 첫 거래일(t0) **시가**, 청산: `t0+h-1` 종가. `excess_return_h = 종목 - SPY(동일 구간)`.
- Split: chronological (Train ≤2017-12-24, Val 2018, Test 2019-01~2020-06) + 7일 embargo. random split 없음.
- 분류 threshold(30/70 분위), winsorize 한계, feature z-score 통계는 **train 으로만** 산출.
- `include_ticker_in_text: false` — ticker 평균 성과 암기를 막고, `B0_ticker_prior` baseline 으로 shortcut 크기를 측정.
- 코드 내 assert: `feature_date < entry_date`, `feature_date <= event_date < entry_date`, split 시간 비중첩.

## 2. 정책 해제/승인된 Python 확보 후 실행 순서

```powershell
# 1) 환경 확인
.venv\Scripts\python.exe -c "import torch,numpy,pandas;print(torch.cuda.is_available())"
# 2) 단위 테스트
.venv\Scripts\python.exe -m pytest training/tests -q
# 3) Smoke test (소량 데이터, 1 epoch)
.venv\Scripts\python.exe scripts\train_event_alpha.py --config configs\training\event_alpha_v0.yaml --smoke --run-id smoke_001
# 4) Full training (백그라운드, 로그 파일)
$env:PYTHONUNBUFFERED='1'
Start-Process .venv\Scripts\python.exe -ArgumentList "scripts\train_event_alpha.py","--config","configs\training\event_alpha_v0.yaml","--run-id","event_alpha_v0_run1" -RedirectStandardOutput logs\training\event_alpha_v0_run1.stdout.log -RedirectStandardError logs\training\event_alpha_v0_run1.stderr.log -WindowStyle Hidden -PassThru
# 5) 이어서 학습 (중단 후)
.venv\Scripts\python.exe scripts\train_event_alpha.py --config configs\training\event_alpha_v0.yaml --resume event_alpha_v0_run1
```

모니터링:
```powershell
Get-Content logs\training\event_alpha_v0_run1.stdout.log -Tail 30 -Wait   # 로그
Get-Content artifacts\event_alpha\event_alpha_v0_run1\training_status.json # 현재 상태 (30초 heartbeat)
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv -l 5       # GPU
Get-Process python | Select Id,CPU,StartTime                              # 프로세스
```

## 3. Remote Monitor (Supabase → Vercel) 설정

1. Supabase SQL editor 에서 `infra/db/init/04_training_monitor.sql` 실행.
2. 본인 이메일 등록: `INSERT INTO vt.admin_users(email) VALUES ('<your-email>');`
3. Supabase → Settings → API → **Exposed schemas** 에 `vt` 포함 확인 (기존 대시보드와 동일).
4. 학습 머신 `training/.env` (커밋 금지) 에 설정:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — **학습 머신에만**. 로그에 출력되지 않음.
5. Vercel 환경변수 (기존과 동일, 신규 secret 없음):
   `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `ALLOWED_EMAIL`
   (`/training` 은 service_role 을 쓰지 않고 사용자 세션 + RLS 로 읽는다.)
6. 배포: `cd web && vercel` (기존 Vercel 프로젝트 연결 후). 접속: `/training`, `/training/<run_id>`.

보안 요약: `/training` 은 미로그인 시 `/login` 으로 이동, `ALLOWED_EMAIL` 이 비어 있으면 거부(fail-closed),
RLS 는 `vt.is_admin()` 등록 계정만 SELECT. 쓰기는 학습 머신(service_role)만 가능. 원격 제어(stop/start/주문) 기능 없음.
전송 데이터: 상태/heartbeat/metric/체크포인트 *이름*/sanitize 된 로그 15줄. dataset/checkpoint/traceback 전문/절대경로는 전송하지 않음.

## 4. 산출물 (`artifacts/event_alpha/<run_id>/`)

`config.yaml`, `run_manifest.json`, `metrics.json`, `baselines.json`, `test_predictions.csv`, `training.log`,
`training_status.json`, `training_metrics.jsonl`, `label_statistics.json`, `data_split_statistics.json`,
`feature_info.json`, `training_curve.png`, `confusion_matrix.png`, `top_k_alpha.png`, `checkpoints/{best,last}.pt`

## 5. 알려진 한계 (해석 시 주의)

- 헤드라인만, 날짜 단위 → 장중 반응/뉴스 선반영을 구분할 수 없음. 가격 반응이 이미 일어난 뒤의 뉴스일 수 있음.
- survivorship bias (Yahoo 에서 사라진 종목 제외), 한 날짜·종목에 여러 헤드라인 → 샘플 간 상관.
- Test 기간(2019–2020-06)에 COVID 급락 포함. 단일 시장 체제의 결과로 일반화 금지.
- top-k 시뮬레이션은 연구용: 겹치는 보유기간, 유동성, 체결 가능성 미반영.
- 테스트 split 은 모델 선택(best epoch = val macro-F1)에 사용하지 않았음.
