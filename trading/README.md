# trading/ — VeloTrade 자동매매 모듈

본인 전용 자동 추적·알림·리밸런싱·매매 봇. Alpaca(미국 주식)·Binance(글로벌 코인)·Upbit(국내 코인) 멀티 어댑터, 룰 기반(RSI/MA/그리드) + LLM 시그널(VeloTrade RAG 연동) 전략 지원.

> ⚠️ **Paper trading 우선**. 실거래는 백테스트 + paper에서 충분히 검증한 뒤 별도 플래그(`--live`)로 활성. 손실은 본인 책임.

## 디렉토리 구조

```
trading/
├── pyproject.toml
├── .env.example
├── configs/
│   ├── strategies.example.yaml   # 전략 파라미터
│   └── universe.example.yaml     # 종목 리스트
├── scripts/
│   ├── run_bot.py                # 실시간 봇 실행
│   └── run_backtest.py           # 백테스트
├── src/velotrade_trading/
│   ├── core/                     # 도메인 모델·포트폴리오·리스크
│   │   ├── types.py
│   │   ├── portfolio.py
│   │   └── risk.py
│   ├── adapters/                 # 거래소 어댑터 (Strategy 패턴)
│   │   ├── base.py
│   │   ├── paper.py              # 시뮬레이션 (모든 거래소 공통 가능)
│   │   ├── alpaca.py             # 미국 주식
│   │   ├── binance.py            # 글로벌 코인
│   │   └── upbit.py              # 국내 코인
│   ├── strategies/               # 매매 전략 (Strategy 패턴)
│   │   ├── base.py
│   │   ├── rsi.py
│   │   ├── ma_cross.py
│   │   └── llm_signal.py         # VeloTrade RAG → 시그널
│   ├── runner/
│   │   ├── bot.py                # 이벤트 루프
│   │   └── alerts.py             # Discord/Slack/Email
│   └── cli.py                    # `python -m velotrade_trading`
└── tests/
```

## 개념

| 개념 | 설명 |
|------|------|
| **Adapter** | 거래소별 API를 공통 인터페이스로 추상화. `get_quote`, `submit_order`, `get_positions`, `stream_quotes` 등. |
| **Strategy** | 시세·이벤트 → `Signal(side, size, confidence, reasoning)`. 거래소를 모름. |
| **Risk Manager** | 시그널 → 검증된 주문. 포지션 크기, 일일 손실 한도, 종목 집중도 등. |
| **Bot** | 어댑터·전략·리스크를 결합한 이벤트 루프. paper/live 모드 분리. |
| **Portfolio** | 현재 보유 포지션 + 가용 자본. DB(Supabase) 동기화. |

## 빠른 시작 (Paper)

```powershell
cd trading
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]

# .env.example → .env 복사 후 API 키 입력 (paper 키만 있으면 OK)
copy .env.example .env

# 설정
copy configs/strategies.example.yaml configs/strategies.yaml
copy configs/universe.example.yaml configs/universe.yaml

# Paper 봇 실행 (실거래 X)
python -m velotrade_trading run --mode paper --config configs/strategies.yaml
```

## 거래소별 paper / live 옵션

| 거래소 | Paper | Live | 비고 |
|--------|-------|------|------|
| Alpaca | ✅ 공식 Paper API (별도 키) | ✅ 미국 계좌 필요 | 주식·ETF |
| Binance | ✅ Testnet | ✅ KYC 필요 | 글로벌 코인 |
| Upbit | ⚠️ Testnet 없음 → 내부 시뮬레이션 어댑터로 대체 | ✅ 국내 KYC | KRW 마켓 |

Upbit는 Testnet이 없으므로 paper 모드에서는 `adapters/paper.py`의 시뮬레이터가 Upbit 시세를 받아 가상 주문을 처리합니다.

## 안전장치

1. `--mode paper`가 **기본값**. `--live`는 명시적으로 줘야 활성.
2. `RiskManager`에서 단일 거래·일일·종목별 한도 강제. 한도 초과 시그널은 reject.
3. `--dry-run` 플래그로 시그널만 출력하고 어댑터 호출 차단.
4. 출금/입금 권한은 거래소 API 키 발급 시 끄기 (트레이딩만).
5. 모든 주문은 `vt.orders` 테이블에 기록 (Supabase).

## 14일 MVP 일정 (자동매매 통합)

[`ROADMAP.md`](../ROADMAP.md) 참고.
