"""meta.models — the pinned model ladder for meta-labeling (v3).

Ladder (pinned BEFORE any fit on a family, sha ledgered): calibrated L2 logistic is the
baseline; LightGBM (small fixed grid) is promoted ONLY if its purged-CV AUC beats logistic
by >= 0.01 AND its Brier score is not worse. Artifacts are frozen with a model card; the
artifact sha inside an exam pin makes the trained model part of the pre-registration —
retraining after the pin = a different candidate.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from ..canon import sha256_canon

LADDER = {
    "models": ["logistic_l2", "lightgbm"],
    "lgbm_grid": [{"num_leaves": 7, "n_estimators": 60, "learning_rate": 0.05,
                   "min_child_samples": 50, "reg_lambda": 5.0}],
    "promotion": "lgbm only if CV AUC >= logistic + 0.01 AND Brier not worse",
    "calibration": "isotonic (out-of-fold)",
}


def pin_ladder(family_id: str, out_dir: Path, ledger) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = sha256_canon(LADDER)
    p = out_dir / f"ladder_{family_id}.json"
    if not p.exists():
        p.write_text(json.dumps({"family_id": family_id, "ladder": LADDER,
                                 "ladder_sha256": sha}, indent=1))
        ledger.append("meta.ladder_pinned", {"family_id": family_id, "ladder_sha256": sha})
    return sha


def _oof(model_fn, X, y, folds):
    """Out-of-fold probabilities (NaN where never in a test fold)."""
    proba = np.full(len(y), np.nan)
    for tr, te in folds:
        med = np.nanmedian(X[tr], axis=0)
        Xtr = np.where(np.isnan(X[tr]), med, X[tr])
        Xte = np.where(np.isnan(X[te]), med, X[te])
        m = model_fn()
        m.fit(Xtr, y[tr])
        proba[te] = m.predict_proba(Xte)[:, 1]
    return proba


def fit_ladder(df: pd.DataFrame, feature_cols: list[str], folds, family_id: str,
               out_dir: Path, ledger) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    pin_ladder(family_id, out_dir, ledger)
    d = df.sort_values("entry_ts").reset_index(drop=True)
    X = d[feature_cols].to_numpy(dtype=float)
    y = (d["profit"].to_numpy() > 0).astype(int)

    def logi():
        return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
    cand = {"logistic_l2": logi}
    try:
        from lightgbm import LGBMClassifier
        g = LADDER["lgbm_grid"][0]
        cand["lightgbm"] = lambda: LGBMClassifier(**g, verbosity=-1)
    except ImportError:
        pass
    scores = {}
    for name, fn in cand.items():
        p = _oof(fn, X, y, folds)
        m = ~np.isnan(p)
        scores[name] = {"auc": round(float(roc_auc_score(y[m], p[m])), 4),
                        "brier": round(float(brier_score_loss(y[m], p[m])), 4)}
    winner = "logistic_l2"
    if ("lightgbm" in scores
            and scores["lightgbm"]["auc"] >= scores["logistic_l2"]["auc"] + 0.01
            and scores["lightgbm"]["brier"] <= scores["logistic_l2"]["brier"]):
        winner = "lightgbm"
    med = np.nanmedian(X, axis=0)
    final = cand[winner]()
    final.fit(np.where(np.isnan(X), med, X), y)
    blob = pickle.dumps({"model": final, "features": feature_cols, "median_impute": med})
    sha = sha256_canon({"family": family_id, "winner": winner, "scores": scores})[:12]
    art = out_dir / f"model_{sha}.pkl"
    art.write_bytes(blob)
    card = {"family_id": family_id, "winner": winner, "scores": scores,
            "features": feature_cols, "n_trades": len(d), "artifact": art.name}
    (out_dir / f"model_{sha}.card.json").write_text(json.dumps(card, indent=1))
    ledger.append("meta.model_fitted", {k: card[k] for k in
                                        ("family_id", "winner", "scores", "artifact")})
    return card
