"""CPU baselines. GPU transformer 가 정말 baseline 을 이기는지 비교하기 위한 기준선.

  B0  ticker prior      : train 에서 ticker 별 다수 클래스 / 평균 alpha (shortcut 이 얼마나 되는지 측정)
  B-A Logistic (market) : 시장 feature 만
  B-A2 TF-IDF + market  : SGD(log-loss) — 텍스트 신호 baseline
  B-B LightGBM (market) : 시장 feature 만 (+ 설치돼 있을 때)

모든 fit 은 train split 만 사용. val 은 보고용, test 는 최종 보고용(선택에 사용 금지).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ..metrics import cls_metrics, reg_metrics

log = logging.getLogger("event_alpha")


def _report(name: str, y_cls: np.ndarray, pred: np.ndarray, y_reg: np.ndarray, alpha: np.ndarray) -> dict:
    return {"name": name, **cls_metrics(y_cls, pred), **reg_metrics(y_reg, alpha)}


def run_baselines(
    df: pd.DataFrame, X: np.ndarray, cls_h: int, eval_splits: tuple[str, ...] = ("val", "test")
) -> dict[str, Any]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression, SGDClassifier
    from scipy.sparse import csr_matrix, hstack

    ycol = f"y_reg_{cls_h}d"
    tr = (df["split"] == "train").to_numpy()
    res: dict[str, Any] = {"cls_horizon": cls_h}

    def sl(split: str) -> np.ndarray:
        return (df["split"] == split).to_numpy()

    def alpha_from_proba(p: np.ndarray, scale: float) -> np.ndarray:
        return (p[:, 2] - p[:, 0]) * scale  # P(UP)-P(DOWN) → alpha 점수

    scale = float(df.loc[tr, ycol].std())

    # B0 ticker prior
    prior_cls = df[tr].groupby("ticker")["y_cls"].agg(lambda s: int(s.mode().iloc[0]))
    prior_alpha = df[tr].groupby("ticker")[ycol].mean()
    out0 = {}
    for s in eval_splits:
        m = sl(s)
        pred = df.loc[m, "ticker"].map(prior_cls).fillna(1).astype(int).to_numpy()
        al = df.loc[m, "ticker"].map(prior_alpha).fillna(0.0).to_numpy()
        out0[s] = _report("ticker_prior", df.loc[m, "y_cls"].to_numpy(), pred, df.loc[m, ycol].to_numpy(), al)
    res["B0_ticker_prior"] = out0

    # B-A logistic on market features
    clf = LogisticRegression(max_iter=300, class_weight="balanced")
    clf.fit(X[tr], df.loc[tr, "y_cls"].to_numpy())
    outA = {}
    for s in eval_splits:
        m = sl(s)
        p = clf.predict_proba(X[m])
        outA[s] = _report("logreg_market", df.loc[m, "y_cls"].to_numpy(), p.argmax(1),
                          df.loc[m, ycol].to_numpy(), alpha_from_proba(p, scale))
    res["BA_logreg_market"] = outA

    # B-A2 tfidf + market (SGD)
    tf = TfidfVectorizer(max_features=50000, ngram_range=(1, 2), min_df=3, sublinear_tf=True)
    Xt_tr = tf.fit_transform(df.loc[tr, "headline"])
    sgd = SGDClassifier(loss="log_loss", alpha=2e-6, max_iter=15, tol=None,
                        class_weight="balanced", random_state=42)
    sgd.fit(hstack([Xt_tr, csr_matrix(X[tr])]).tocsr(), df.loc[tr, "y_cls"].to_numpy())
    outT = {}
    for s in eval_splits:
        m = sl(s)
        Xm = hstack([tf.transform(df.loc[m, "headline"]), csr_matrix(X[m])]).tocsr()
        p = sgd.predict_proba(Xm)
        outT[s] = _report("tfidf_sgd_market", df.loc[m, "y_cls"].to_numpy(), p.argmax(1),
                          df.loc[m, ycol].to_numpy(), alpha_from_proba(p, scale))
    res["BA2_tfidf_market"] = outT

    # B-B LightGBM
    try:
        import lightgbm as lgb

        gbm = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                                 subsample=0.8, colsample_bytree=0.8, class_weight="balanced",
                                 random_state=42, verbose=-1)
        va = sl("val")
        gbm.fit(X[tr], df.loc[tr, "y_cls"].to_numpy(),
                eval_set=[(X[va], df.loc[va, "y_cls"].to_numpy())],  # early-stop 은 val 만 사용
                callbacks=[lgb.early_stopping(30, verbose=False)])
        outG = {}
        for s in eval_splits:
            m = sl(s)
            p = gbm.predict_proba(X[m])
            outG[s] = _report("lightgbm_market", df.loc[m, "y_cls"].to_numpy(), p.argmax(1),
                              df.loc[m, ycol].to_numpy(), alpha_from_proba(p, scale))
        res["BB_lightgbm_market"] = outG
    except ImportError:
        res["BB_lightgbm_market"] = "SKIPPED: lightgbm not installed"
    return res
