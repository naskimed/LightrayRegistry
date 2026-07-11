"""meta.gate — the Tier-3 hard brake: do the features predict trade outcomes AT ALL? (v3)

Purged, embargoed, time-blocked cross-validation on masked-train trades. The gate passes
only if (a) mean CV AUC >= auc_floor AND (b) it beats the q95 of the same pipeline run on
20 circularly-shifted label copies (the internal scramble control — the twin battery in
AUC space, which also calibrates the CV itself: scrambles clearing the floor more than
~1/20 means the CV leaks). Fail => STOP: nothing downstream is ever fitted.

This is the lesson SGL taught, priced at seconds of compute: clustering/models can only
amplify signal that exists; this gate measures whether any exists.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SCRAMBLE_SEED = 909090


def purged_time_folds(entry_ts, exit_ts, n_folds: int = 5,
                      embargo_days: float = 2.0) -> list[tuple[np.ndarray, np.ndarray]]:
    """Contiguous time blocks as test folds; train rows whose [entry, exit] lifetime
    overlaps the embargoed test span are PURGED. Mirrors tierb semantics at CV scale."""
    e = pd.to_datetime(pd.Series(list(entry_ts))).reset_index(drop=True)
    x = pd.to_datetime(pd.Series(list(exit_ts))).reset_index(drop=True)
    order = np.argsort(e.to_numpy())
    n = len(e)
    folds = []
    edges = [int(round(i * n / n_folds)) for i in range(n_folds + 1)]
    emb = pd.Timedelta(days=embargo_days)
    for f in range(n_folds):
        test_idx = order[edges[f]:edges[f + 1]]
        if len(test_idx) == 0:
            continue
        t0, t1 = e.iloc[test_idx].min() - emb, x.iloc[test_idx].max() + emb
        overlap = ((e < t1) & (x > t0)).to_numpy()
        train_idx = np.where(~overlap)[0]
        train_idx = np.setdiff1d(train_idx, test_idx)
        if len(train_idx) >= 50 and len(test_idx) >= 20:
            folds.append((train_idx, test_idx))
    return folds


def _cv_auc(X: np.ndarray, y: np.ndarray, folds) -> float:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler
    aucs = []
    for tr, te in folds:
        if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            continue
        med = np.nanmedian(X[tr], axis=0)
        Xtr = np.where(np.isnan(X[tr]), med, X[tr])
        Xte = np.where(np.isnan(X[te]), med, X[te])
        sc = StandardScaler().fit(Xtr)
        clf = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(Xtr), y[tr])
        aucs.append(roc_auc_score(y[te], clf.predict_proba(sc.transform(Xte))[:, 1]))
    return float(np.mean(aucs)) if aucs else float("nan")


def feature_gate(df: pd.DataFrame, feature_cols: list[str], auc_floor: float = 0.55,
                 n_scrambles: int = 20, n_folds: int = 5,
                 embargo_days: float = 2.0) -> dict:
    """df = masked-train trades (entry_ts, exit_ts, profit + feature columns)."""
    d = df.sort_values("entry_ts").reset_index(drop=True)
    X = d[feature_cols].to_numpy(dtype=float)
    y = (d["profit"].to_numpy() > 0).astype(int)
    folds = purged_time_folds(d["entry_ts"], d["exit_ts"], n_folds, embargo_days)
    auc = _cv_auc(X, y, folds)
    rng = np.random.RandomState(SCRAMBLE_SEED)
    scr = []
    for _ in range(n_scrambles):
        k = int(rng.randint(1, len(y) - 1))
        scr.append(_cv_auc(X, np.roll(y, k), folds))
    q95 = float(np.nanquantile(scr, 0.95))
    return {"auc": round(auc, 4), "scramble_q95": round(q95, 4),
            "scramble_over_floor": int(np.sum(np.asarray(scr) >= auc_floor)),
            "n_features": len(feature_cols), "n_trades": len(d), "n_folds": len(folds),
            "auc_floor": auc_floor,
            "passes": bool(auc >= auc_floor and auc > q95)}
