"""Event Alpha v0 학습 엔트리포인트.

  python scripts/train_event_alpha.py --config configs/training/event_alpha_v0.yaml [--smoke] [--resume RUN_ID]

학습 모델은 alpha 추정만 한다. 주문/거래소 API 는 호출하지 않는다.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

# .env 는 선택(Supabase telemetry 용). 값은 로그에 출력하지 않는다.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "training" / ".env")
except ImportError:
    pass

from event_alpha.train import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
