"""Event Alpha v0 학습 오케스트레이션.

흐름: config → processed dataset(leakage assert) → baselines → GPU multi-task fine-tune
      → best(val macro-F1) 선택 → test 1회 평가 → artifacts 저장.
test split 은 모델/하이퍼파라미터 선택에 사용하지 않는다.
"""

from __future__ import annotations

import argparse
import collections
import logging
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
import yaml

from . import MODEL_VERSION
from .config import REPO_ROOT, Config, load_config
from .dataset import build_processed, tokenize_texts
from .evaluate import full_evaluation, predict, prediction_frame, save_plots
from .features import MARKET_FEATURES, PriceDataNotAvailable, apply_feature_stats, fit_feature_stats
from .labels import label_distribution
from .metrics import cls_metrics, reg_metrics
from .models.baseline import run_baselines
from .models.transformer import EventAlphaModel
from .split import split_summary
from .utils import (atomic_write_json, env_info, git_commit, make_run_id, sanitize_text,
                    set_seed, setup_logging)

log = logging.getLogger("event_alpha")


class _TailHandler(logging.Handler):
    def __init__(self, n: int) -> None:
        super().__init__()
        self.buf: collections.deque[str] = collections.deque(maxlen=n)

    def emit(self, record: logging.LogRecord) -> None:
        self.buf.append(self.format(record))

    def tail(self) -> str:
        return sanitize_text("\n".join(self.buf))


def _autocast_dtype(pref: str) -> torch.dtype | None:
    if not torch.cuda.is_available() or pref == "fp32":
        return None
    if pref == "bf16" or (pref == "auto" and torch.cuda.is_bf16_supported()):
        return torch.bfloat16
    return torch.float16


def _lr_factor(progress: float, warmup: float) -> float:
    if progress < warmup:
        return max(progress / max(warmup, 1e-9), 1e-3)
    return max(0.0, (1.0 - progress) / max(1.0 - warmup, 1e-9))


def _subsample_time_ordered(idx: np.ndarray, limit: int | None) -> np.ndarray:
    if limit is None or len(idx) <= limit:
        return idx
    return idx[np.linspace(0, len(idx) - 1, limit).astype(int)]


class Trainer:
    def __init__(self, cfg: Config, run_dir: Path, ids: torch.Tensor, X: torch.Tensor, Y: torch.Tensor,
                 y_cls: torch.Tensor, df: pd.DataFrame, tgt_stats: dict, rep: Any,
                 tail: _TailHandler) -> None:
        self.cfg, self.run_dir = cfg, run_dir
        self.ids, self.X, self.Y, self.y_cls = ids, X, Y, y_cls
        self.df, self.tgt_stats, self.rep, self.tail = df, tgt_stats, rep, tail
        self.horizons = cfg.label.horizons
        self.ckpt_dir = run_dir / "checkpoints"
        self.ckpt_dir.mkdir(parents=True, exist_ok=True)
        self.dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.amp = _autocast_dtype(cfg.train.precision)
        split = df["split"].to_numpy()
        tr = np.where(split == "train")[0]
        va = np.where(split == "val")[0]
        self.train_idx = _subsample_time_ordered(tr, cfg.train.max_train_samples)
        self.val_idx = _subsample_time_ordered(va, cfg.train.max_eval_samples)

    # ------------------------------------------------------------------------------
    def _build(self) -> tuple[EventAlphaModel, torch.optim.Optimizer]:
        c = self.cfg
        model = EventAlphaModel(
            c.path(c.paths.pretrained_dir), len(MARKET_FEATURES), len(self.horizons),
            c.model.market_hidden, c.model.dropout,
        ).to(self.dev)
        opt = torch.optim.AdamW(model.param_groups(c.train.lr, c.train.head_lr, c.train.weight_decay))
        return model, opt

    def _save(self, name: str, model, opt, state: dict) -> None:
        tmp = self.ckpt_dir / f".{name}.tmp"
        torch.save({"model": model.state_dict(), "optimizer": opt.state_dict(), **state}, tmp)
        tmp.replace(self.ckpt_dir / name)

    def _loss(self, logits, reg, b) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        ce = F.cross_entropy(logits.float(), self.y_cls[b])
        hub = F.smooth_l1_loss(reg.float(), self.Y[b])
        return ce + self.cfg.model.reg_loss_weight * hub, ce, hub

    def evaluate_val(self, model) -> dict[str, float]:
        c = self.cfg
        lg, rg = predict(model, self.ids, self.X, self.val_idx, c.train.eval_batch_size, self.amp)
        yc = self.y_cls[torch.as_tensor(self.val_idx, device=self.dev)].cpu().numpy()
        Yv = self.Y[torch.as_tensor(self.val_idx, device=self.dev)].cpu().numpy()
        ce = float(F.cross_entropy(torch.from_numpy(lg), torch.from_numpy(yc).long()))
        hub = float(F.smooth_l1_loss(torch.from_numpy(rg), torch.from_numpy(Yv)))
        m = cls_metrics(yc, lg.argmax(1))
        j = self.horizons.index(c.label.cls_horizon)
        st = self.tgt_stats[c.label.cls_horizon]
        y_raw = Yv[:, j] * st["std"] + st["mean"]
        p_raw = rg[:, j] * st["std"] + st["mean"]
        r = reg_metrics(y_raw, p_raw)
        return {"val_loss": ce + c.model.reg_loss_weight * hub, "val_ce": ce, "val_reg": hub,
                "accuracy": m["accuracy"], "macro_f1": m["macro_f1"], "mae": r["mae"],
                "rmse": r["rmse"], "spearman_ic": r["spearman_ic"]}

    # ------------------------------------------------------------------------------
    def fit(self, batch_size: int, resume: bool) -> dict[str, Any]:
        c = self.cfg
        model, opt = self._build()
        state = {"epoch": 0, "samples_in_epoch": 0, "global_samples": 0, "global_step": 0,
                 "best_f1": -1.0, "best_epoch": -1, "bad_epochs": 0, "history": []}
        last = self.ckpt_dir / "last.pt"
        if resume and last.exists():
            ck = torch.load(last, map_location=self.dev, weights_only=False)
            model.load_state_dict(ck["model"])
            opt.load_state_dict(ck["optimizer"])
            state = {k: ck[k] for k in state}
            log.info("RESUMED from %s epoch=%d samples_in_epoch=%d", last.name, state["epoch"],
                     state["samples_in_epoch"])
        n = len(self.train_idx)
        total_samples = c.train.epochs * n
        total_steps = c.train.epochs * math.ceil(n / batch_size)
        scaler = torch.amp.GradScaler("cuda", enabled=self.amp == torch.float16)
        t_start, run_loss, run_n = time.monotonic(), 0.0, 0
        self.rep.update(total_epochs=c.train.epochs, total_steps=total_steps, status="RUNNING")

        for epoch in range(state["epoch"], c.train.epochs):
            perm = np.random.default_rng(c.train.seed + epoch).permutation(n)
            start = state["samples_in_epoch"]
            model.train()
            pos = start
            while pos < n:
                bidx = self.train_idx[perm[pos : pos + batch_size]]
                b = torch.as_tensor(bidx, device=self.dev)
                prog = state["global_samples"] / total_samples
                f = _lr_factor(prog, c.train.warmup_ratio)
                for g in opt.param_groups:
                    g["lr"] = g["base_lr"] * f
                with torch.autocast("cuda", dtype=self.amp) if self.amp else torch.autocast("cpu", enabled=False):
                    logits, reg = model(self.ids[b].long(), self.X[b])
                loss, ce, hub = self._loss(logits, reg, b)
                opt.zero_grad(set_to_none=True)
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), c.train.grad_clip)
                scaler.step(opt)
                scaler.update()

                pos += len(bidx)
                state["samples_in_epoch"] = pos
                state["global_samples"] += len(bidx)
                state["global_step"] += 1
                run_loss += float(loss.detach()) * len(bidx)
                run_n += len(bidx)
                s = state["global_step"]

                if s % c.train.log_every_steps == 0:
                    tl = run_loss / max(run_n, 1)
                    el = time.monotonic() - t_start
                    log.info("epoch %d/%d step %d/%d loss=%.4f lr=%.2e %.0f samp/s", epoch + 1,
                             c.train.epochs, s, total_steps, tl, opt.param_groups[0]["lr"],
                             run_n / max(el, 1e-9))
                    self.rep.update(current_epoch=epoch + 1, current_step=s, train_loss=tl,
                                    progress=state["global_samples"] / total_samples,
                                    learning_rate=opt.param_groups[0]["lr"],
                                    log_tail=self.tail.tail())
                    self.rep.log_metrics("train", epoch + 1, s, {"train_loss": tl})
                if s % c.train.checkpoint_every_steps == 0:
                    self._save("last.pt", model, opt, {**state, "batch_size": batch_size})
                    self.rep.log_checkpoint("checkpoints/last.pt")

            # --- epoch 종료: validation ------------------------------------------------
            train_loss = run_loss / max(run_n, 1)
            run_loss, run_n = 0.0, 0
            vm = self.evaluate_val(model)
            state["epoch"] = epoch + 1
            state["samples_in_epoch"] = 0
            rec = {"epoch": epoch + 1, "train_loss": train_loss, **vm}
            state["history"].append(rec)
            log.info("VAL epoch %d: %s", epoch + 1,
                     {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rec.items()})
            self.rep.update(current_epoch=epoch + 1, train_loss=train_loss, val_loss=vm["val_loss"],
                            accuracy=vm["accuracy"], macro_f1=vm["macro_f1"], mae=vm["mae"],
                            rmse=vm["rmse"], spearman_ic=vm["spearman_ic"], log_tail=self.tail.tail())
            self.rep.log_metrics("val", epoch + 1, state["global_step"],
                                 {k: v for k, v in rec.items() if k != "epoch"})
            improved = vm["macro_f1"] > state["best_f1"]
            if improved:
                state.update(best_f1=vm["macro_f1"], best_epoch=epoch + 1, bad_epochs=0)
                self._save("best.pt", model, opt, {**state, "batch_size": batch_size})
                self.rep.log_checkpoint(f"checkpoints/best_epoch_{epoch + 1:02d}")
            else:
                state["bad_epochs"] += 1
            self._save("last.pt", model, opt, {**state, "batch_size": batch_size})
            if state["bad_epochs"] > c.train.early_stopping_patience:
                log.info("early stopping at epoch %d", epoch + 1)
                break
        return {"state": state, "batch_size": batch_size, "total_steps": total_steps}


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Event Alpha v0 training (research only; no orders)")
    p.add_argument("--config", required=True)
    p.add_argument("--smoke", action="store_true", help="소규모 smoke test (1 epoch, 소량 샘플)")
    p.add_argument("--run-id", default=None)
    p.add_argument("--resume", default=None, help="이어서 학습할 run_id (artifacts/event_alpha/<run_id>)")
    p.add_argument("--skip-baselines", action="store_true")
    p.add_argument("--batch-size", type=int, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    overrides: dict[str, Any] = {}
    if args.smoke:
        overrides.update({"data.max_events": 6000, "train.max_train_samples": 1500,
                          "train.max_eval_samples": 500, "train.epochs": 1,
                          "train.checkpoint_every_steps": 5, "train.log_every_steps": 2,
                          "train.batch_size": 64, "train.early_stopping_patience": 0})
    if args.batch_size:
        overrides["train.batch_size"] = args.batch_size
    cfg = load_config(args.config, overrides)

    run_id = args.resume or args.run_id or make_run_id("smoke" if args.smoke else "event_alpha_v0")
    run_dir = cfg.path(cfg.paths.artifacts_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(run_dir / "training.log")
    shared_log = cfg.path(cfg.paths.log_dir)
    shared_log.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(shared_log / f"{run_id}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    tail = _TailHandler(cfg.monitor.log_tail_lines)
    tail.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(tail)

    from monitoring.reporter import build_reporter

    rep, sb_msg = build_reporter(run_dir, run_id, cfg.monitor.supabase_enabled,
                                 cfg.monitor.heartbeat_seconds, cfg.monitor.supabase_every_seconds)
    env = env_info()
    log.info("run_id=%s smoke=%s %s", run_id, args.smoke, sb_msg)
    log.info("env: %s", {k: env.get(k) for k in ("gpu_name", "gpu_vram_mb", "cuda_version",
                                                 "torch_version", "cuda_available")})
    set_seed(cfg.train.seed)
    with open(run_dir / "config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg.model_dump(), f, allow_unicode=True, sort_keys=False)

    rep.start_run({
        "run_id": run_id, "experiment_name": cfg.experiment_name, "model_name": MODEL_VERSION,
        "hostname": env.get("hostname"), "gpu_name": env.get("gpu_name"),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_commit": git_commit(REPO_ROOT),
        "total_epochs": cfg.train.epochs, "current_epoch": 0, "current_step": 0, "progress": 0.0,
    })

    try:
        if not torch.cuda.is_available():
            log.warning("CUDA not available — running on CPU (slow)")
        df, meta = build_processed(cfg)
        df = df[df["split"] != "embargo"].reset_index(drop=True)
        log.info("processed events=%d %s", len(df), split_summary(df))

        tok_dir = cfg.path(cfg.paths.pretrained_dir)
        ids_np = tokenize_texts(df["text"].tolist(), tok_dir, cfg.model.max_length)

        tr_mask = df["split"] == "train"
        fstats = fit_feature_stats(df[tr_mask], MARKET_FEATURES)  # train 통계만
        X_np = apply_feature_stats(df, MARKET_FEATURES, fstats)
        tgt_stats = {h: {"mean": float(df.loc[tr_mask, f"y_reg_{h}d"].mean()),
                         "std": float(df.loc[tr_mask, f"y_reg_{h}d"].std())}
                     for h in cfg.label.horizons}
        Y_np = np.stack([(df[f"y_reg_{h}d"].to_numpy() - tgt_stats[h]["mean"]) / tgt_stats[h]["std"]
                         for h in cfg.label.horizons], axis=1).astype(np.float32)

        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        ids = torch.from_numpy(ids_np).to(dev)
        X = torch.from_numpy(X_np).to(dev)
        Y = torch.from_numpy(Y_np).to(dev)
        y_cls = torch.from_numpy(df["y_cls"].to_numpy().astype(np.int64)).to(dev)

        manifest: dict[str, Any] = {
            "run_id": run_id, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "git_commit": git_commit(REPO_ROOT), **env, "model_version": MODEL_VERSION,
            "pretrained_encoder_dir": cfg.paths.pretrained_dir, "seed": cfg.train.seed,
            "smoke_test": args.smoke, "supabase_telemetry": sb_msg,
            "data_source": "ashraq/financial-news (headline-only, date-only) + Yahoo chart daily OHLCV",
            "known_limitations": [
                "headline only (no article body); date granularity (no intraday time)",
                "survivorship bias: tickers missing from Yahoo (delisted) are absent",
                "news ends 2020-06; test period includes COVID crash regime",
            ],
            "periods": split_summary(df), "label_distribution": label_distribution(df),
            "label_thresholds_train_only": meta["thresholds_train_only"],
            "feature_columns": MARKET_FEATURES, "feature_stats_train_only": fstats,
            "target_stats_train_only": tgt_stats,
            "text_includes_ticker": cfg.data.include_ticker_in_text,
        }
        atomic_write_json(run_dir / "label_statistics.json",
                          {"distribution": manifest["label_distribution"],
                           "thresholds": meta["thresholds_train_only"], "target_stats": tgt_stats})
        atomic_write_json(run_dir / "data_split_statistics.json", manifest["periods"])
        atomic_write_json(run_dir / "feature_info.json",
                          {"features": MARKET_FEATURES, "stats": fstats})

        # --- baselines ------------------------------------------------------------
        if not args.skip_baselines:
            log.info("running CPU baselines ...")
            rep.update(log_tail="running baselines")
            try:
                base = run_baselines(df, X_np, cfg.label.cls_horizon)
                atomic_write_json(run_dir / "baselines.json", base)
                for k, v in base.items():
                    if isinstance(v, dict):
                        for s in ("val", "test"):
                            if s in v:
                                log.info("BASELINE %s %s acc=%.4f f1=%.4f ic=%s", k, s,
                                         v[s]["accuracy"], v[s]["macro_f1"], v[s]["spearman_ic"])
            except Exception as e:  # noqa: BLE001 — baseline 실패가 GPU 학습을 막지 않게
                log.warning("baselines failed: %r", e)

        trainer = Trainer(cfg, run_dir, ids, X, Y, y_cls, df, tgt_stats, rep, tail)
        bs = cfg.train.batch_size
        resume = args.resume is not None
        result = None
        for attempt in range(cfg.train.max_oom_retries + 1):
            try:
                result = trainer.fit(bs, resume)
                break
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                new_bs = max(8, bs // 2)
                log.error("CUDA OOM at batch_size=%d (attempt %d). retry with batch_size=%d "
                          "from last checkpoint if present", bs, attempt + 1, new_bs)
                if new_bs == bs or attempt >= cfg.train.max_oom_retries:
                    raise
                bs, resume = new_bs, True
        assert result is not None
        manifest.update({"final_batch_size": result["batch_size"], "total_steps": result["total_steps"],
                         "epochs_run": result["state"]["epoch"],
                         "best_epoch": result["state"]["best_epoch"],
                         "precision": str(trainer.amp)})

        # --- best checkpoint 로 test 1회 평가 --------------------------------------
        model, _ = trainer._build()
        ck = torch.load(run_dir / "checkpoints" / "best.pt", map_location=dev, weights_only=False)
        model.load_state_dict(ck["model"])
        manifest["n_parameters"] = int(sum(p.numel() for p in model.parameters()))
        te_idx = _subsample_time_ordered(np.where(df["split"].to_numpy() == "test")[0],
                                         cfg.train.max_eval_samples)
        lg, rg = predict(model, ids, X, te_idx, cfg.train.eval_batch_size, trainer.amp)
        pred = prediction_frame(df.iloc[te_idx], lg, rg, tgt_stats, cfg.label.horizons,
                                cfg.eval.signal_horizon)
        pred.to_csv(run_dir / "test_predictions.csv", index=False)
        test_eval = full_evaluation(pred, cfg)
        metrics = {"history": result["state"]["history"], "best_val_macro_f1": result["state"]["best_f1"],
                   "test": test_eval, "test_used_for_selection": False}
        atomic_write_json(run_dir / "metrics.json", metrics)
        save_plots(run_dir, result["state"]["history"], test_eval)
        manifest["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        atomic_write_json(run_dir / "run_manifest.json", manifest)
        log.info("TEST macro_f1=%.4f acc=%.4f IC3d=%s", test_eval["classification"]["macro_f1"],
                 test_eval["classification"]["accuracy"], test_eval["regression_3d"]["spearman_ic"])
        rep.complete({"macro_f1": result["state"]["best_f1"], "log_tail": tail.tail()})
        log.info("DONE run_dir=%s", run_dir)
        return 0
    except KeyboardInterrupt:
        rep.fail("interrupted by user", interrupted=True)
        log.error("interrupted")
        return 130
    except PriceDataNotAvailable as e:
        rep.fail(str(e))
        log.error("%s", e)
        return 2
    except Exception as e:  # noqa: BLE001
        log.error("FAILED: %s\n%s", e, traceback.format_exc())
        rep.fail(f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
