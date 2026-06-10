from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "data"
RAW_DIR = STORE / "raw"
CACHE_DIR = STORE / "cache"
FEATURES_DIR = STORE / "features"
OUTPUTS_DIR = STORE / "outputs"
CATALOG_PATH = STORE / "catalog.csv"
FEATURE_CATALOG_PATH = STORE / "feature_catalog.csv"

SUPPORTED_TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
PRIORITY_SYMBOLS = {"XAUUSD","NAS100","US30","XTIUSD","GBPJPY","EURUSD","USDJPY","USDCAD","GBPUSD","EURJPY"}
HORIZON = {"M1":240, "M5":72, "M15":48, "M30":32, "H1":72, "H4":48, "D1":30}


def ensure_store():
    for p in [STORE, RAW_DIR, CACHE_DIR, FEATURES_DIR, OUTPUTS_DIR]:
        p.mkdir(parents=True, exist_ok=True)


def logger_default(msg: str):
    print(msg)


def parse_symbol_tf(path: Path) -> Tuple[Optional[str], Optional[str]]:
    m = re.search(r"(.+?)_(M1|M5|M15|M30|H1|H4|D1)_", path.name.upper())
    if not m:
        return None, None
    symbol = m.group(1).replace("-", "").replace(" ", "").strip()
    return symbol, m.group(2)


def market_files():
    out = []
    for p in RAW_DIR.rglob("*"):
        if not p.is_file():
            continue
        sym, tf = parse_symbol_tf(p)
        if sym and tf:
            out.append(p)
    return sorted(out)


def read_csv_flexible(path: Path) -> pd.DataFrame:
    last = None
    for sep in [",", ";", "\t"]:
        try:
            df = pd.read_csv(path, sep=sep)
            cols = [str(c).strip().lower() for c in df.columns]
            if {"time","open","high","low","close"}.issubset(set(cols)):
                df.columns = cols
                return df
        except Exception as e:
            last = e
    raise RuntimeError(f"Could not parse {path.name}: {last}")


def cache_path(symbol: str, tf: str) -> Path:
    return CACHE_DIR / f"{symbol}_{tf}.pkl"


def feature_path(symbol: str, tf: str) -> Path:
    return FEATURES_DIR / f"{symbol}_{tf}_features.pkl"


def list_catalog() -> List[dict]:
    if not CATALOG_PATH.exists():
        return []
    return pd.read_csv(CATALOG_PATH).fillna("").to_dict("records")


def list_feature_catalog() -> List[dict]:
    if not FEATURE_CATALOG_PATH.exists():
        return []
    return pd.read_csv(FEATURE_CATALOG_PATH).fillna("").to_dict("records")


def import_raw_data(logger: Callable[[str], None] = logger_default) -> dict:
    ensure_store()
    files = market_files()
    rows = []
    logger(f"Found {len(files)} market files")

    for i, f in enumerate(files, 1):
        sym, tf = parse_symbol_tf(f)
        logger(f"[{i}/{len(files)}] Importing {sym} {tf}: {f.name}")
        df = read_csv_flexible(f)
        keep = [c for c in ["time","open","high","low","close","tick_volume","spread_points","real_volume"] if c in df.columns]
        df = df[keep].copy()
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        for c in ["open","high","low","close","tick_volume","spread_points","real_volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["time","open","high","low","close"]).sort_values("time").drop_duplicates("time").reset_index(drop=True)
        df.to_pickle(cache_path(sym, tf))
        rows.append({
            "symbol": sym, "tf": tf, "rows": len(df),
            "start": str(df["time"].min()), "end": str(df["time"].max()),
            "source": str(f.relative_to(RAW_DIR)),
            "cache": str(cache_path(sym, tf).relative_to(STORE))
        })

    pd.DataFrame(rows).to_csv(CATALOG_PATH, index=False)
    return {"files": len(files), "datasets": rows}


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([(df["high"]-df["low"]), (df["high"]-pc).abs(), (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def build_one_features(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    df = df.copy()
    df["ema21"] = ema(df["close"], 21)
    df["ema55"] = ema(df["close"], 55)
    df["ema200"] = ema(df["close"], 200)
    df["atr14"] = atr(df, 14)
    df["rsi14"] = rsi(df["close"], 14)
    df["range"] = df["high"] - df["low"]
    df["body"] = df["close"] - df["open"]
    df["body_pct"] = df["body"].abs() / df["range"].replace(0, np.nan)
    df["upper_wick"] = df["high"] - df[["open","close"]].max(axis=1)
    df["lower_wick"] = df[["open","close"]].min(axis=1) - df["low"]
    slope_bars = 4 if tf in ["H4","D1"] else 8
    df["ema21_slope_atr"] = (df["ema21"] - df["ema21"].shift(slope_bars)) / df["atr14"].replace(0, np.nan)
    df["atr_rank_500"] = df["atr14"].rolling(500, min_periods=50).rank(pct=True)

    t = pd.to_datetime(df["time"])
    df["date"] = t.dt.date.astype(str)
    df["hour"] = t.dt.hour
    df["minute"] = t.dt.minute
    df["weekday"] = t.dt.weekday
    df["year"] = t.dt.year
    df["month"] = t.dt.month

    daily = df.groupby("date").agg(day_high=("high","max"), day_low=("low","min"), day_close=("close","last"))
    daily["prev_day_high"] = daily["day_high"].shift(1)
    daily["prev_day_low"] = daily["day_low"].shift(1)
    daily["prev_day_close"] = daily["day_close"].shift(1)
    df = df.merge(daily[["prev_day_high","prev_day_low","prev_day_close"]], left_on="date", right_index=True, how="left")

    if tf in ["M1","M5","M15","M30","H1"]:
        asian = df[(df["hour"] >= 0) & (df["hour"] < 7)].groupby("date").agg(asian_high=("high","max"), asian_low=("low","min"))
        df = df.merge(asian, left_on="date", right_index=True, how="left")
    else:
        df["asian_high"] = np.nan
        df["asian_low"] = np.nan

    return df


def build_features(logger: Callable[[str], None] = logger_default) -> dict:
    ensure_store()
    if not CATALOG_PATH.exists():
        raise RuntimeError("No catalog found. Run import first.")
    cat = pd.read_csv(CATALOG_PATH)
    rows = []
    logger(f"Building features for {len(cat)} datasets")
    for i, r in cat.iterrows():
        sym, tf = r["symbol"], r["tf"]
        logger(f"[{i+1}/{len(cat)}] Features {sym} {tf}")
        df = pd.read_pickle(cache_path(sym, tf))
        fdf = build_one_features(df, tf)
        fdf.to_pickle(feature_path(sym, tf))
        row = r.to_dict()
        row["feature_cache"] = str(feature_path(sym, tf).relative_to(STORE))
        row["feature_rows"] = len(fdf)
        rows.append(row)
    pd.DataFrame(rows).to_csv(FEATURE_CATALOG_PATH, index=False)
    return {"datasets": len(rows), "features": rows}


def session_mask(df: pd.DataFrame, s: str):
    if s == "all": return pd.Series(True, index=df.index)
    if s == "asian": return (df.hour >= 0) & (df.hour < 7)
    if s == "london": return (df.hour >= 7) & (df.hour < 13)
    if s == "ny": return (df.hour >= 13) & (df.hour < 21)
    if s == "overlap": return (df.hour >= 13) & (df.hour < 17)
    if s == "london_ny": return (df.hour >= 7) & (df.hour < 21)
    return pd.Series(True, index=df.index)


def weekday_mask(df: pd.DataFrame, mode: str):
    if mode == "all": return pd.Series(True, index=df.index)
    if mode == "tue_thu": return df.weekday.isin([1,2,3])
    if mode == "no_friday": return df.weekday != 4
    if mode == "no_monday": return df.weekday != 0
    return pd.Series(True, index=df.index)


def signals(df: pd.DataFrame, concept: str, lookback: int):
    c = df.close
    hi = df.high.rolling(lookback).max().shift(1)
    lo = df.low.rolling(lookback).min().shift(1)
    buy = pd.Series(False, index=df.index)
    sell = pd.Series(False, index=df.index)

    if concept == "breakout_trend":
        buy = (c > hi) & (df.ema21 > df.ema55) & (c > df.ema200) & (df.ema21_slope_atr > 0.03)
        sell = (c < lo) & (df.ema21 < df.ema55) & (c < df.ema200) & (df.ema21_slope_atr < -0.03)
    elif concept == "breakout_fast":
        buy = (c > hi) & (df.ema21 > df.ema55) & (df.ema21_slope_atr > 0)
        sell = (c < lo) & (df.ema21 < df.ema55) & (df.ema21_slope_atr < 0)
    elif concept == "pullback_ema21":
        buy = (df.ema21 > df.ema55) & (c > df.ema21) & (c.shift(1) < df.ema21.shift(1))
        sell = (df.ema21 < df.ema55) & (c < df.ema21) & (c.shift(1) > df.ema21.shift(1))
    elif concept == "compression_breakout":
        comp = df.atr_rank_500 < 0.35
        buy = comp & (c > hi) & (df.ema21 > df.ema55)
        sell = comp & (c < lo) & (df.ema21 < df.ema55)
    elif concept == "sweep_reclaim":
        buy = (df.low < lo) & (c > lo) & (df.rsi14 < 50)
        sell = (df.high > hi) & (c < hi) & (df.rsi14 > 50)
    elif concept == "prev_day_sweep":
        buy = (df.low < df.prev_day_low) & (c > df.prev_day_low) & (df.rsi14 < 50)
        sell = (df.high > df.prev_day_high) & (c < df.prev_day_high) & (df.rsi14 > 50)
    elif concept == "asian_breakout":
        tw = (df.hour >= 7) & (df.hour < 13)
        buy = tw & (c > df.asian_high) & (df.ema21 > df.ema55)
        sell = tw & (c < df.asian_low) & (df.ema21 < df.ema55)
    elif concept == "ny_orb":
        ranges = {}
        for d, g in df.groupby("date", sort=False):
            rg = g[(g.hour >= 13) & (g.hour < 15)]
            if len(rg) > 0:
                ranges[d] = (rg.high.max(), rg.low.min())
        orh = df.date.map(lambda d: ranges.get(d, (np.nan, np.nan))[0])
        orl = df.date.map(lambda d: ranges.get(d, (np.nan, np.nan))[1])
        tw = (df.hour >= 15) & (df.hour < 20)
        buy = tw & (c > orh) & (df.ema21 > df.ema55)
        sell = tw & (c < orl) & (df.ema21 < df.ema55)

    return buy.fillna(False), sell.fillna(False)


def backtest(df: pd.DataFrame, buy, sell, rr: float, sl_mult: float, horizon: int, cost_R: float = 0.04):
    trades = []
    i = 250
    n = len(df)
    while i < n - 2:
        side = 1 if buy.iloc[i] else (-1 if sell.iloc[i] else 0)
        if side == 0:
            i += 1
            continue
        ei = i + 1
        entry = float(df.open.iloc[ei])
        a = float(df.atr14.iloc[i])
        if not np.isfinite(a) or a <= 0:
            i += 1
            continue
        risk = a * sl_mult
        sl = entry - side * risk
        tp = entry + side * risk * rr
        end = min(ei + horizon, n - 1)
        R = None
        for j in range(ei, end + 1):
            hi, lo = float(df.high.iloc[j]), float(df.low.iloc[j])
            hit_sl = lo <= sl if side == 1 else hi >= sl
            hit_tp = hi >= tp if side == 1 else lo <= tp
            if hit_sl and hit_tp:
                R, end = -1 - cost_R, j
                break
            if hit_sl:
                R, end = -1 - cost_R, j
                break
            if hit_tp:
                R, end = rr - cost_R, j
                break
        if R is None:
            R = side * (float(df.close.iloc[end]) - entry) / risk - cost_R
        trades.append({
            "entry_time": df.time.iloc[ei], "exit_time": df.time.iloc[end],
            "side": side, "R": float(R), "year": int(df.year.iloc[ei]),
            "month": int(df.month.iloc[ei]), "hour": int(df.hour.iloc[ei]),
            "weekday": int(df.weekday.iloc[ei])
        })
        i = end + 1
    return pd.DataFrame(trades)


def stats(tr):
    if tr.empty: return None
    R = tr.R
    gp = float(R[R > 0].sum())
    gl = float(-R[R <= 0].sum())
    eq = R.cumsum()
    dd = float((eq.cummax() - eq).max())
    max_ls, cur = 0, 0
    for x in R:
        if x <= 0:
            cur += 1
            max_ls = max(max_ls, cur)
        else:
            cur = 0
    return {"n": len(R), "sumR": float(R.sum()), "expR": float(R.mean()), "pf": float(gp / gl if gl > 0 else np.inf), "winrate": float((R > 0).mean()), "maxDD_R": dd, "max_loss_streak": max_ls}


def robust(tr):
    out = {}
    for name, sub in [("train", tr[tr.entry_time < pd.Timestamp("2024-01-01")]), ("test", tr[tr.entry_time >= pd.Timestamp("2024-01-01")])]:
        s = stats(sub)
        for k in ["n","sumR","expR","pf","winrate","maxDD_R","max_loss_streak"]:
            out[f"{name}_{k}"] = s[k] if s else np.nan
    yrs = []
    for y, sub in tr.groupby("year"):
        s = stats(sub)
        if s: yrs.append([int(y), int(s["n"]), float(s["sumR"]), float(s["pf"])])
    out["year_details"] = json.dumps(yrs)
    out["tested_years"] = sum(1 for y,n,s,p in yrs if n >= 10)
    out["positive_years"] = sum(1 for y,n,s,p in yrs if n >= 10 and s > 0)
    return out


def list_outputs() -> List[dict]:
    if not OUTPUTS_DIR.exists():
        return []
    out = []
    for d in sorted([p for p in OUTPUTS_DIR.iterdir() if p.is_dir()], reverse=True):
        cand = d / "candidate_edges.csv"
        allp = d / "all_edges.csv"
        out.append({
            "name": d.name,
            "path": str(d.relative_to(STORE)),
            "candidate_count": int(len(pd.read_csv(cand))) if cand.exists() else 0,
            "all_count": int(len(pd.read_csv(allp))) if allp.exists() else 0,
            "has_report": (d / "QUANTLAB_REPORT.md").exists()
        })
    return out


def read_edges_preview(scan_name: str, kind: str = "candidate", limit: int = 100):
    filename = {
        "candidate": "candidate_edges.csv",
        "all": "all_edges.csv",
        "rejected": "rejected_edges.csv"
    }.get(kind, "candidate_edges.csv")
    p = OUTPUTS_DIR / scan_name / filename
    if not p.exists():
        return {"rows": [], "columns": []}
    df = pd.read_csv(p).head(limit).replace([np.inf, -np.inf], np.nan).fillna("")
    return {"rows": df.to_dict("records"), "columns": list(df.columns)}


def select_pairs(mode: str, symbols: str, tfs: str):
    cat = pd.read_csv(CATALOG_PATH)
    sym_filter = [x.strip().upper() for x in symbols.split(",") if x.strip()] if symbols else []
    tf_filter = [x.strip().upper() for x in tfs.split(",") if x.strip()] if tfs else []
    pairs = []
    for _, r in cat.iterrows():
        sym, tf = r.symbol, r.tf
        if sym_filter and sym not in sym_filter: continue
        if tf_filter and tf not in tf_filter: continue
        if mode == "priority" and sym not in PRIORITY_SYMBOLS: continue
        if mode == "htf" and tf not in ["H1","H4","D1"]: continue
        if mode == "intraday" and tf not in ["M5","M15","M30"]: continue
        pairs.append((sym, tf))
    return pairs


def run_scan(name: str, mode: str = "priority", symbols: str = "", tfs: str = "", min_trades: int = 40, min_pf: float = 1.22, min_test_pf: float = 1.08, logger: Callable[[str], None] = logger_default):
    ensure_store()
    if not CATALOG_PATH.exists():
        raise RuntimeError("No data catalog. Run import first.")
    pairs = select_pairs(mode, symbols, tfs)
    outdir = OUTPUTS_DIR / name
    outdir.mkdir(parents=True, exist_ok=True)
    logger(f"Scan {name}: mode={mode} datasets={len(pairs)}")

    results = []
    datasets = []
    t0 = time.time()
    for i, (sym, tf) in enumerate(pairs, 1):
        fp = feature_path(sym, tf)
        if not fp.exists():
            logger(f"[{i}/{len(pairs)}] SKIP no features: {sym} {tf}")
            continue
        df = pd.read_pickle(fp)
        datasets.append({"symbol": sym, "tf": tf, "rows": len(df), "start": str(df.time.min()), "end": str(df.time.max())})
        logger(f"[{i}/{len(pairs)}] {sym} {tf} rows={len(df)}")
        concepts = ["breakout_fast","compression_breakout","sweep_reclaim","prev_day_sweep","asian_breakout","ny_orb"] if tf in ["M5","M15","M30"] else ["breakout_trend","breakout_fast","pullback_ema21","compression_breakout","sweep_reclaim","prev_day_sweep"]
        sessions = ["all","london","ny","overlap","london_ny"] if tf in ["M5","M15","M30"] else ["all","london_ny","ny","overlap"]
        lookbacks = [12,20,48] if tf in ["M5","M15","M30"] else [20,50]
        tested = 0
        for concept in concepts:
            lbs = [20] if concept in ["asian_breakout","ny_orb"] else lookbacks
            for lb in lbs:
                b0, s0 = signals(df, concept, lb)
                if int(b0.sum() + s0.sum()) < 20: continue
                for sess in sessions:
                    sm = session_mask(df, sess)
                    for wd in ["all","tue_thu","no_friday"]:
                        wm = weekday_mask(df, wd)
                        b, s = b0 & sm & wm, s0 & sm & wm
                        if int(b.sum() + s.sum()) < 20: continue
                        for rr in [1.0,1.4,2.0]:
                            for slm in [1.0,1.4,2.0]:
                                tr = backtest(df, b, s, rr, slm, HORIZON.get(tf, 48))
                                st = stats(tr)
                                if not st or st["n"] < min_trades: continue
                                rec = {"symbol": sym, "tf": tf, "concept": concept, "lookback": lb, "session": sess, "weekday": wd, "rr": rr, "sl_mult": slm}
                                rec.update(st)
                                rec.update(robust(tr))
                                rec["score"] = rec["expR"]*100 + min(rec["pf"],3)*20 + (0 if pd.isna(rec.get("test_expR", np.nan)) else rec["test_expR"]*80) - rec["maxDD_R"]*.25 - rec["max_loss_streak"]
                                rec["accepted"] = rec["pf"] >= min_pf and rec["n"] >= min_trades and (pd.isna(rec.get("test_pf", np.nan)) or rec.get("test_pf", 0) >= min_test_pf) and rec.get("positive_years",0) >= max(1, int(rec.get("tested_years",0)*.45))
                                results.append(rec)
                                tested += 1
        logger(f"  tested={tested}, elapsed={(time.time()-t0)/60:.1f}m")
        save_scan_outputs(outdir, results, datasets)

    save_scan_outputs(outdir, results, datasets)
    return {"scan_name": name, "datasets": len(datasets), "edges": len(results), "output": str(outdir.relative_to(STORE))}


def save_scan_outputs(outdir: Path, results: List[dict], datasets: List[dict]):
    pd.DataFrame(datasets).to_csv(outdir / "datasets_scanned.csv", index=False)
    if results:
        res = pd.DataFrame(results).sort_values("score", ascending=False)
    else:
        res = pd.DataFrame()
    res.to_csv(outdir / "all_edges.csv", index=False)
    if not res.empty and "accepted" in res:
        res[res.accepted].to_csv(outdir / "candidate_edges.csv", index=False)
        res[~res.accepted].to_csv(outdir / "rejected_edges.csv", index=False)
    else:
        pd.DataFrame().to_csv(outdir / "candidate_edges.csv", index=False)
        pd.DataFrame().to_csv(outdir / "rejected_edges.csv", index=False)
    (outdir / "QUANTLAB_REPORT.md").write_text(report_markdown(outdir.name, res, datasets), encoding="utf-8")


def report_markdown(name: str, res: pd.DataFrame, datasets: List[dict]) -> str:
    lines = [f"# EdgeLab Report — {name}\n\n", f"Datasets scanned: {len(datasets)}\n\n", f"Total edges: {len(res)}\n\n"]
    cand = res[res.accepted] if not res.empty and "accepted" in res else pd.DataFrame()
    lines.append(f"Candidate edges: {len(cand)}\n\n")
    if datasets:
        lines.append("## Datasets\n\n")
        lines.append(pd.DataFrame(datasets).to_markdown(index=False))
        lines.append("\n\n")
    cols = ["symbol","tf","concept","lookback","session","weekday","rr","sl_mult","n","sumR","expR","pf","test_pf","train_pf","winrate","maxDD_R","max_loss_streak","score"]
    if not cand.empty:
        lines.append("## Candidates\n\n")
        lines.append(cand.head(100)[cols].to_markdown(index=False))
        lines.append("\n\n")
    if not res.empty:
        lines.append("## Top tested edges\n\n")
        lines.append(res.head(100)[cols].to_markdown(index=False))
        lines.append("\n\n")
    return "".join(lines)
