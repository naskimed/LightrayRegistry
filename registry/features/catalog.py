"""catalog — the NS2 feature canon, computed bars-only and target-blind.

The AFML-lineage feature families (returns/stationarity, volatility estimators, trend/momentum,
distributional, serial-dependence, MICROSTRUCTURAL, time) as a single registry both the SGL
geometry and the SJM input reference. Every feature is a function of bars up to and including t —
never t+1 — so it is knowable at the entry decision (target-blind by construction). The
microstructural family is the genuinely new capability: it consumes Binance volume/quote_volume/
taker_buy_base, which the price-only belka6 set (and the zerovol legacy feed) never could.

Each feature carries (family, window) provenance; the redundancy screen kills collinear mass
downstream — the discipline is register-then-screen, not curate-by-hand.

Input: a bars DataFrame indexed by time with columns Open/High/Low/Close and (for the micro
family) volume/quote_volume/taker_buy_base. Output: a feature DataFrame, same index.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ── stationarity: fractional differentiation (AFML) — fixed-width window weights ──────────────
def _ffd_weights(d: float, thres: float = 1e-4, max_k: int = 200) -> np.ndarray:
    w = [1.0]
    for k in range(1, max_k):
        w_ = -w[-1] * (d - k + 1) / k
        if abs(w_) < thres:
            break
        w.append(w_)
    return np.array(w[::-1])


def frac_diff(series: pd.Series, d: float) -> pd.Series:
    w = _ffd_weights(d)
    width = len(w)
    out = series.rolling(width).apply(lambda x: np.dot(w, x), raw=True)
    return out


# ── volatility estimators (all annualization-free, one window each) ──────────────────────────
def parkinson(h, l, n):
    return (np.log(h / l) ** 2).rolling(n).mean().pipe(np.sqrt) / (2 * np.sqrt(np.log(2)))


def garman_klass(o, h, l, c, n):
    rs = 0.5 * np.log(h / l) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2
    return rs.rolling(n).mean().clip(lower=0).pipe(np.sqrt)


def rogers_satchell(o, h, l, c, n):
    rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    return rs.rolling(n).mean().clip(lower=0).pipe(np.sqrt)


def yang_zhang(o, h, l, c, n):
    lo, hc = np.log(o / c.shift(1)), np.log(c / o)
    sig_o = lo.rolling(n).var()
    sig_c = hc.rolling(n).var()
    sig_rs = (np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)).rolling(n).mean()
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    return (sig_o + k * sig_c + (1 - k) * sig_rs).clip(lower=0).pipe(np.sqrt)


# ── trend / momentum ─────────────────────────────────────────────────────────────────────────
def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def macd_hist(c, fast=12, slow=26, sig=9):
    macd = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    return macd - macd.ewm(span=sig, adjust=False).mean()


def bb_pctb(c, n):
    m, s = c.rolling(n).mean(), c.rolling(n).std()
    return (c - (m - 2 * s)) / (4 * s)


def lr_slope(c, n):
    x = np.arange(n)
    xm = x.mean()
    denom = ((x - xm) ** 2).sum()
    return np.log(c).rolling(n).apply(lambda y: ((x - xm) * (y - y.mean())).sum() / denom, raw=True)


def adx(h, l, c, n):
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = pd.Series(tr, index=c.index).ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=c.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus, index=c.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


# ── serial dependence / complexity ───────────────────────────────────────────────────────────
def variance_ratio(ret, q, n):
    """Lo-MacKinlay VR(q): var of q-period returns / (q * var of 1-period). VR<1 mean-revert."""
    v1 = ret.rolling(n).var()
    vq = ret.rolling(n).sum().rolling(q).mean()  # proxy q-agg
    return (ret.rolling(q).sum().rolling(n).var()) / (q * v1)


def rolling_autocorr(x, n, lag):
    return x.rolling(n).apply(lambda s: pd.Series(s).autocorr(lag), raw=False)


# ── microstructural (the NEW family — Binance volume/taker) ───────────────────────────────────
def corwin_schultz(h, l):
    b = (np.log(h / l) ** 2 + np.log(h.shift(1) / l.shift(1)) ** 2)
    hl2 = pd.concat([h, h.shift(1)], axis=1).max(axis=1) / pd.concat([l, l.shift(1)], axis=1).min(axis=1)
    g = np.log(hl2) ** 2
    a = (np.sqrt(2 * b) - np.sqrt(b)) / (3 - 2 * np.sqrt(2)) - np.sqrt(g / (3 - 2 * np.sqrt(2)))
    return (2 * (np.exp(a) - 1) / (1 + np.exp(a))).clip(lower=0)


def roll_spread(c, n):
    dc = c.diff()
    cov = dc.rolling(n).cov(dc.shift(1))
    return 2 * np.sqrt((-cov).clip(lower=0))


# ── the catalog ───────────────────────────────────────────────────────────────────────────────
def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = bars["Open"], bars["High"], bars["Low"], bars["Close"]
    lr = np.log(c / c.shift(1))
    f: dict[str, pd.Series] = {}

    # returns / stationarity
    for k in (1, 5, 20, 50):
        f[f"ret_{k}"] = np.log(c / c.shift(k))
    f["fracdiff_d04"] = frac_diff(np.log(c), 0.4)
    f["fracdiff_d06"] = frac_diff(np.log(c), 0.6)

    # volatility estimators
    for n in (20, 50):
        f[f"rv_{n}"] = lr.rolling(n).std()
        f[f"parkinson_{n}"] = parkinson(h, l, n)
        f[f"yangzhang_{n}"] = yang_zhang(o, h, l, c, n)
    f["garmanklass_20"] = garman_klass(o, h, l, c, 20)
    f["rogerssatchell_20"] = rogers_satchell(o, h, l, c, 20)
    f["vol_ratio_5_50"] = lr.rolling(5).std() / lr.rolling(50).std()
    f["vol_of_vol_20"] = lr.rolling(20).std().rolling(20).std()

    # trend / momentum
    f["rsi_14"] = rsi(c, 14)
    f["roc_10"] = c / c.shift(10) - 1
    f["macd_hist"] = macd_hist(c)
    f["bb_pctb_20"] = bb_pctb(c, 20)
    f["lr_slope_20"] = lr_slope(c, 20)
    f["adx_14"] = adx(h, l, c, 14)
    f["ema_dist_20"] = c / c.ewm(span=20, adjust=False).mean() - 1

    # distributional / shape
    f["skew_50"] = lr.rolling(50).skew()
    f["kurt_50"] = lr.rolling(50).kurt()
    f["zscore_20"] = (c - c.rolling(20).mean()) / c.rolling(20).std()
    f["tsrank_50"] = c.rolling(50).apply(lambda s: (s.iloc[-1] > s).mean(), raw=False)
    f["clv"] = (2 * c - h - l) / (h - l).replace(0, np.nan)

    # serial dependence / complexity
    f["autocorr_5"] = rolling_autocorr(lr, 50, 5)
    f["var_ratio_2"] = variance_ratio(lr, 2, 50)

    # microstructural (volume — new)
    if "quote_volume" in bars:
        qv = bars["quote_volume"].replace(0, np.nan)
        f["amihud_20"] = (lr.abs() / qv).rolling(20).mean()
        f["vol_zscore_50"] = (bars["volume"] - bars["volume"].rolling(50).mean()) / bars["volume"].rolling(50).std()
        vwap = (c * bars["volume"]).rolling(20).sum() / bars["volume"].rolling(20).sum()
        f["vwap_dist"] = c / vwap - 1
    if "taker_buy_base" in bars:
        imb = (2 * bars["taker_buy_base"] / bars["volume"].replace(0, np.nan) - 1)
        f["taker_imb"] = imb
        f["taker_imb_ma20"] = imb.rolling(20).mean()
    f["corwin_schultz"] = corwin_schultz(h, l)
    f["roll_spread_20"] = roll_spread(c, 20)

    # time encodings (server clock handled upstream via the index tz)
    hour = bars.index.hour
    f["hour_sin"] = pd.Series(np.sin(2 * np.pi * hour / 24), index=bars.index)
    f["hour_cos"] = pd.Series(np.cos(2 * np.pi * hour / 24), index=bars.index)
    f["dow"] = pd.Series(bars.index.dayofweek.astype(float), index=bars.index)

    return pd.DataFrame(f, index=bars.index)


def attach_to_population(rows: list[dict], bars: pd.DataFrame) -> tuple[list[dict], list[str]]:
    """Join the target-blind catalog onto population rows at each trade's entry bar. Adds
    fc_<name> columns (fc = feature-catalog); the join is a pure lookup at entry_ts, so it
    inherits the catalog's target-blindness. `bars` must be the SAME signal bars the population
    was generated on (naive-UTC index matching entry_ts)."""
    F = compute_features(bars)
    cols = list(F.columns)
    idx = F.index
    # map entry_ts (ISO string) -> catalog row via exact index lookup
    Fd = {ts.isoformat(sep=" "): F.loc[ts].to_dict() for ts in idx}
    out = []
    for r in rows:
        row = dict(r)
        key = str(r["entry_ts"])
        fr = Fd.get(key) or Fd.get(key[:19])   # tolerate second-precision
        for c in cols:
            v = fr.get(c) if fr else None
            row[f"fc_{c}"] = float(v) if v is not None and v == v else float("nan")
        out.append(row)
    return out, [f"fc_{c}" for c in cols]


FAMILIES = {
    "returns_stationarity": ["ret_1", "ret_5", "ret_20", "ret_50", "fracdiff_d04", "fracdiff_d06"],
    "volatility": ["rv_20", "rv_50", "parkinson_20", "parkinson_50", "yangzhang_20", "yangzhang_50",
                   "garmanklass_20", "rogerssatchell_20", "vol_ratio_5_50", "vol_of_vol_20"],
    "trend_momentum": ["rsi_14", "roc_10", "macd_hist", "bb_pctb_20", "lr_slope_20", "adx_14", "ema_dist_20"],
    "distributional": ["skew_50", "kurt_50", "zscore_20", "tsrank_50", "clv"],
    "serial_complexity": ["autocorr_5", "var_ratio_2"],
    "microstructural": ["amihud_20", "vol_zscore_50", "vwap_dist", "taker_imb", "taker_imb_ma20",
                        "corwin_schultz", "roll_spread_20"],
    "time": ["hour_sin", "hour_cos", "dow"],
}
