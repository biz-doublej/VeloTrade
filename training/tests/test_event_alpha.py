"""Event Alpha 단위 테스트 (GPU/네트워크 불필요).

실행: .venv\\Scripts\\python.exe -m pytest training/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from event_alpha.config import Config, SplitConfig  # noqa: E402
from event_alpha.inference import FORBIDDEN_KEYS, assert_contract, make_record  # noqa: E402
from event_alpha.labels import classify, fit_thresholds, forward_window_return  # noqa: E402
from event_alpha.config import LabelConfig  # noqa: E402
from event_alpha.split import assert_chronological, assign_split  # noqa: E402
from event_alpha.utils import atomic_write_json, mask_secrets, sanitize_text  # noqa: E402


def test_forward_window_return_uses_next_open_to_future_close():
    o = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    c = np.array([10.5, 11.5, 12.5, 13.5, 14.5])
    r = forward_window_return(o, c, np.array([1]), 3)  # open[1]=11 → close[3]=13.5
    assert r[0] == pytest.approx(13.5 / 11.0 - 1)
    # 범위를 넘는 horizon 은 NaN (미래 데이터를 만들어내지 않는다)
    assert np.isnan(forward_window_return(o, c, np.array([4]), 3)[0])


def test_split_is_chronological_and_has_embargo():
    d = pd.Series(pd.to_datetime(["2016-06-01", "2017-12-30", "2018-06-01", "2018-12-30", "2019-03-01"]))
    s = assign_split(d, SplitConfig(train_end="2017-12-31", val_end="2018-12-31", embargo_days=7))
    assert s.tolist() == ["train", "embargo", "val", "embargo", "test"]
    df = pd.DataFrame({"event_date": d, "split": s, "ticker": "A"})
    assert_chronological(df[df["split"] != "embargo"])


def test_thresholds_use_train_only():
    cfg = LabelConfig()
    train = pd.Series(np.linspace(-0.1, 0.1, 1001))
    thr = fit_thresholds(train, cfg)
    test_like = pd.Series([-0.5, 0.0, 0.5])  # test 분포가 극단이어도 threshold 는 불변
    assert thr == fit_thresholds(train, cfg)
    assert classify(test_like, thr).tolist() == [0, 1, 2]


def test_contract_has_no_order_fields():
    rec = make_record("AAPL", "e1", "2019-01-02T21:00:00+00:00", np.array([0.1, 0.2, 0.7]),
                      {1: 0.003, 3: 0.012, 5: 0.018})
    assert rec["direction"] == "UP" and rec["model_version"] == "event-alpha-v0"
    assert not (FORBIDDEN_KEYS & set(rec))
    with pytest.raises(ValueError):
        assert_contract({**rec, "quantity": 10})


def test_secrets_and_paths_are_sanitized():
    t = "SUPABASE_SERVICE_ROLE_KEY=abc123secret at C:\\Users\\someone\\work\\x.py"
    out = sanitize_text(t)
    assert "abc123secret" not in out and "someone" not in out
    assert "***" in mask_secrets("api_key: sk-abcdefghijklmnopqrstuvwxyz")


def test_atomic_write_json(tmp_path: Path):
    p = tmp_path / "s.json"
    atomic_write_json(p, {"a": 1})
    atomic_write_json(p, {"a": 2})
    assert p.read_text(encoding="utf-8").count('"a": 2') == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_supabase_reporter_failure_never_raises():
    from monitoring.reporter import SupabaseReporter

    r = SupabaseReporter("http://127.0.0.1:9", "dummy-key", "run_x", timeout=0.5)
    r.start_run({"experiment_name": "t"})      # 연결 실패해도 예외 없음
    r.heartbeat({"progress": 0.5})
    r.log_metrics("val", 1, 10, {"macro_f1": 0.5})
    r.fail("boom C:\\Users\\someone\\x")


def test_config_validation():
    with pytest.raises(ValueError):
        Config.model_validate({"split": {"train_end": "2019-01-01", "val_end": "2018-01-01"}})
