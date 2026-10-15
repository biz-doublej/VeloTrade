"""예측 + 최종 test 평가 + 플롯. test 평가는 best checkpoint 선택이 끝난 뒤 1회만 수행한다."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from .config import Config
from .inference import make_record
from .labels import CLASS_NAMES
from .metrics import cls_metrics, daily_ic, reg_metrics, topk_analysis

log = logging.getLogger("event_alpha")


@torch.no_grad()
def predict(model, ids: torch.Tensor, X: torch.Tensor, idx: np.ndarray, batch_size: int,
            autocast_dtype: torch.dtype | None) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    logits_all, reg_all = [], []
    dev = X.device
    for i in range(0, len(idx), batch_size):
        b = torch.as_tensor(idx[i : i + batch_size], device=dev)
        ctx = torch.autocast("cuda", dtype=autocast_dtype) if autocast_dtype else nullcontext()
        with ctx:
            lg, rg = model(ids[b].long(), X[b])
        logits_all.append(lg.float().cpu())
        reg_all.append(rg.float().cpu())
    return torch.cat(logits_all).numpy(), torch.cat(reg_all).numpy()


def prediction_frame(df: pd.DataFrame, logits: np.ndarray, reg_std: np.ndarray,
                     tgt_stats: dict[int, dict[str, float]], horizons: list[int],
                     signal_horizon: int = 3) -> pd.DataFrame:
    z = logits - logits.max(1, keepdims=True)
    probs = np.exp(z) / np.exp(z).sum(1, keepdims=True)
    alphas = {h: reg_std[:, j] * tgt_stats[h]["std"] + tgt_stats[h]["mean"]
              for j, h in enumerate(horizons)}
    recs = []
    for i, (tk, eid, fd) in enumerate(zip(df["ticker"], df["event_id"], df["feature_date"], strict=True)):
        ts = f"{pd.Timestamp(fd).date()}T21:00:00+00:00"  # as-of: feature_date 종가 이후
        recs.append(make_record(tk, eid, ts, probs[i], {h: alphas[h][i] for h in horizons}))
    out = pd.DataFrame(recs)
    for c in ("p_down", "p_neutral", "p_up"):
        out[c] = probs[:, ["p_down", "p_neutral", "p_up"].index(c)]
    out["alpha_score"] = alphas[signal_horizon]
    for c in ("event_date", "entry_date", "split", "y_cls"):
        out[c] = df[c].to_numpy()
    for h in horizons:
        out[f"excess_return_{h}d"] = df[f"excess_return_{h}d"].to_numpy()
    return out


def full_evaluation(pred: pd.DataFrame, cfg: Config) -> dict[str, Any]:
    h = cfg.eval.signal_horizon
    ret_col = f"excess_return_{h}d"
    res: dict[str, Any] = {"n": int(len(pred))}
    res["classification"] = cls_metrics(pred["y_cls"].to_numpy(), pred[["p_down", "p_neutral", "p_up"]]
                                        .to_numpy().argmax(1))
    for hh in cfg.label.horizons:
        res[f"regression_{hh}d"] = reg_metrics(pred[f"excess_return_{hh}d"].to_numpy(),
                                               pred[f"alpha_{hh}d"].to_numpy())
    res["daily_ic_alpha"] = daily_ic(pred, "alpha_score", ret_col)
    pred = pred.assign(conf_up=pred["p_up"] - pred["p_down"])
    res["topk_by_alpha"] = topk_analysis(pred, "alpha_score", ret_col, cfg.eval.top_fracs,
                                         cfg.eval.cost_bps_scenarios)
    res["topk_by_p_up_minus_p_down"] = topk_analysis(pred, "conf_up", ret_col, cfg.eval.top_fracs,
                                                     cfg.eval.cost_bps_scenarios)
    res["disclaimer"] = ("research-only long-only analysis; ignores overlapping holds, liquidity, "
                         "survivorship bias; NOT connected to any trading system")
    return res


def save_plots(run_dir: Path, history: list[dict], test_eval: dict[str, Any] | None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if history:
        ep = [h["epoch"] for h in history]
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
        ax[0].plot(ep, [h.get("train_loss") for h in history], marker="o", label="train")
        ax[0].plot(ep, [h.get("val_loss") for h in history], marker="o", label="val")
        ax[0].set_title("loss"); ax[0].set_xlabel("epoch"); ax[0].legend()
        ax[1].plot(ep, [h.get("macro_f1") for h in history], marker="o", label="val macro-F1")
        ax[1].plot(ep, [h.get("spearman_ic") for h in history], marker="o", label="val IC(3d)")
        ax[1].set_title("val metrics"); ax[1].set_xlabel("epoch"); ax[1].legend()
        fig.tight_layout(); fig.savefig(run_dir / "training_curve.png", dpi=110); plt.close(fig)
    if test_eval:
        cm = np.asarray(test_eval["classification"]["confusion_matrix"])
        fig, ax = plt.subplots(figsize=(3.8, 3.4))
        ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(3), CLASS_NAMES); ax.set_yticks(range(3), CLASS_NAMES)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, int(cm[i, j]), ha="center", va="center", fontsize=8)
        ax.set_xlabel("pred"); ax.set_ylabel("true"); ax.set_title("test confusion")
        fig.tight_layout(); fig.savefig(run_dir / "confusion_matrix.png", dpi=110); plt.close(fig)
        tk = test_eval["topk_by_alpha"]
        keys = [k for k in tk if k.startswith("top_")]
        fig, ax = plt.subplots(figsize=(5, 3.4))
        ax.bar(keys, [tk[k]["mean_excess"] * 1e4 for k in keys])
        ax.axhline(tk["universe_mean_excess"] * 1e4, color="r", ls="--", label="all events")
        ax.set_ylabel("mean 3d excess (bps)"); ax.set_title("test: top-k by alpha"); ax.legend()
        fig.tight_layout(); fig.savefig(run_dir / "top_k_alpha.png", dpi=110); plt.close(fig)
