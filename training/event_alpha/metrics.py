"""평가 지표 — ML metric + 트레이딩 관점(top-k alpha) 연구용 분석.

주의: top-k 분석은 연구용 단순 시뮬레이션이다. 겹치는 보유기간, 유동성, 체결 가능성,
survivorship bias 를 반영하지 않으므로 실거래 성과의 근거로 쓰면 안 된다.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score


def cls_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=[0, 1, 2], zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1, 2]).tolist(),
    }


def spearman_ic(y: np.ndarray, p: np.ndarray) -> float | None:
    if len(y) < 3 or np.std(p) == 0 or np.std(y) == 0:
        return None
    v = spearmanr(p, y).statistic
    return None if v is None or np.isnan(v) else float(v)


def daily_ic(df: pd.DataFrame, pred_col: str, y_col: str, min_n: int = 10) -> dict[str, float | None]:
    """날짜별 cross-sectional Spearman IC 의 평균/ICIR."""
    ics = []
    for _, g in df.groupby("event_date"):
        if len(g) >= min_n:
            v = spearman_ic(g[y_col].to_numpy(), g[pred_col].to_numpy())
            if v is not None:
                ics.append(v)
    if not ics:
        return {"ic_mean": None, "icir": None, "n_days": 0}
    a = np.asarray(ics)
    return {"ic_mean": float(a.mean()), "icir": float(a.mean() / a.std()) if a.std() > 0 else None,
            "n_days": int(len(a))}


def reg_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    err = p - y
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "spearman_ic": spearman_ic(y, p),
    }


def topk_analysis(
    df: pd.DataFrame, score_col: str, ret_col: str, fracs: list[float], cost_bps: list[float]
) -> dict[str, Any]:
    """score 상위 frac 이벤트를 long-only 로 가정했을 때의 초과수익 통계 (연구용)."""
    out: dict[str, Any] = {"universe_mean_excess": float(df[ret_col].mean()), "n_total": int(len(df))}
    order = df[score_col].rank(method="first", ascending=False)
    for f in fracs:
        k = max(1, int(round(len(df) * f)))
        sel = df[order <= k]
        r = sel[ret_col].to_numpy()
        entry = {
            "n_signals": int(len(sel)),
            "mean_excess": float(np.mean(r)),
            "median_excess": float(np.median(r)),
            "hit_rate": float(np.mean(r > 0)),
            "scenarios": {},
        }
        for c in cost_bps:
            net = sel[ret_col] - c / 1e4  # 왕복 비용(bps) 가정
            daily = net.groupby(sel["entry_date"]).mean()
            entry["scenarios"][f"{c:g}bps"] = {
                "mean_net_excess": float(net.mean()),
                "hit_rate_net": float((net > 0).mean()),
                # 일별 평균 net excess 의 단순 합 (복리 아님, 겹치는 보유기간 무시 → 낙관적일 수 있음)
                "cum_sum_daily_mean": float(daily.sum()),
                "n_days_with_signal": int(len(daily)),
            }
        out[f"top_{f:g}"] = entry
    return out
