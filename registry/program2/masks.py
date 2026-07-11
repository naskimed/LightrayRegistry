"""program2.masks — the forward-only train mask (v3).

Everything the Program-2 free layer computes uses THIS mask, never raw tierb_train_mask:
masked train = the v0.6.2 window/embargo purge AND strictly before the virgin span that
the quarterly epoch exams (and the W4' re-anchor) certify on. The virgin boundary gets the
same left-embargo as a window edge so trades opened just before it can't straddle it.
"""
from __future__ import annotations

import pandas as pd

from ..bridges.vbt_runner import tierb_train_mask

VIRGIN_START = "2026-07-01"


def forward_train_mask(entry_ts, mask_cfg: dict, virgin_start: str = VIRGIN_START):
    """tierb_train_mask ∧ pre-virgin. Same return contract: (is_train, win_id, counts)."""
    is_train, win_id, counts = tierb_train_mask(entry_ts, mask_cfg)
    edge = (pd.Timestamp(virgin_start)
            - pd.Timedelta(days=mask_cfg["embargo"]["left_d"]))
    is_train &= (pd.to_datetime(pd.Series(list(entry_ts))) < edge).to_numpy()
    return is_train, win_id, counts
