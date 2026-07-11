"""meta.decorrelate — feature-decorrelation clustering (the surviving legitimate use of
clustering #2): group redundant features on masked train, keep one medoid per cluster.
Train-only, deterministic, recorded in the model card. Never touches labels.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def select_features(df: pd.DataFrame, feature_cols: list[str],
                    dist_threshold: float = 0.5) -> list[str]:
    """Hierarchical clustering on 1-|Spearman|; medoid (max mean |corr| within cluster)
    per cluster. Features with no variance or >50% NaN are dropped first."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    X = df[feature_cols]
    keep = [c for c in feature_cols
            if X[c].notna().mean() > 0.5 and X[c].nunique(dropna=True) > 2]
    if len(keep) < 2:
        return keep
    corr = X[keep].corr(method="spearman").abs().fillna(0.0)
    np.fill_diagonal(corr.values, 1.0)
    dist = squareform((1 - corr).to_numpy(), checks=False)
    labels = fcluster(linkage(dist, method="average"), t=dist_threshold,
                      criterion="distance")
    chosen = []
    for cl in sorted(set(labels)):
        members = [keep[i] for i in range(len(keep)) if labels[i] == cl]
        if len(members) == 1:
            chosen.append(members[0])
        else:
            sub = corr.loc[members, members]
            chosen.append(sub.mean(axis=1).idxmax())
    return sorted(chosen)
