#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

FINANCIAL_KEYWORDS = ("금융", "은행", "보험", "증권", "카드", "저축은행", "캐피탈")

PORTABLE_FULL_FEATURES = [
    "high_52w_proximity", "ma_ratio_20_120", "ma_ratio_5_60", "momentum_quality",
    "volume_ratio_21d", "amihud_21d", "rolling_beta_60d",
    "roe", "gpa", "sector_zscore_roe", "sector_zscore_gpa",
    "market_regime_120d",
    "sector_momentum_21d", "sector_momentum_63d",
    "sector_relative_momentum_21d", "sector_relative_momentum_63d",
    "sector_zscore_mom_5d", "sector_zscore_mom_21d", "sector_zscore_mom_63d",
    "sector_zscore_mom_126d", "sector_zscore_turnover_21d",
    "sector_zscore_volatility_21d", "sector_zscore_volatility_63d",
    "sector_zscore_drawdown_252d", "sector_zscore_volume_ratio_21d",
    "liquidity_decay_score", "low_price_trap", "distress_composite_score",
    "sector_dispersion", "sector_dispersion_21d", "sector_rotation_signal",
    "earnings_growth_yoy",
]

KR_CORE_PORTABLE = [
    "sector_zscore_volatility_63d",
    "sector_zscore_volatility_21d",
    "ma_ratio_5_60",
    "ma_ratio_20_120",
    "mom_36m",
    "sector_zscore_mom_21d",
    "sector_zscore_roe",
    "gpa",
    "earnings_growth_yoy",
    "amihud_21d",
]

LOWVOL_TREND = [
    ("sector_zscore_volatility_63d", -1.0),
    ("sector_zscore_volatility_21d", -1.0),
    ("ma_ratio_5_60", +1.0),
    ("ma_ratio_20_120", +1.0),
    ("sector_zscore_mom_21d", +1.0),
    ("mom_36m", +1.0),
]


@dataclass(frozen=True)
class Config:
    feature_start: str
    test_start: str
    end: str
    min_market_cap: int = 200_000_000_000
    horizon: int = 42
    train_years: int = 3
    embargo: int = 43
    top_n: int = 50
    buy_rank: int = 28
    hold_rank: int = 90
    buy_cost: float = 0.0035
    sell_cost: float = 0.0055
    initial_capital: float = 100_000_000.0


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--feature-start", required=True)
    p.add_argument("--test-start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", default="outputs/tournament")
    p.add_argument("--workers", type=int, default=1)
    return p.parse_args()


def register_mom36_and_patch_engine(alphakrx_root: Path, db_path: Path, cfg: Config):
    sys.path.insert(0, str(alphakrx_root))
    from ml.features.registry import FeatureGroup, register, get_all_groups
    from ml.features._pipeline import FeatureEngineer

    if not any("mom_36m" in getattr(g, "columns", []) for g in get_all_groups()):
        @register
        class TournamentMom36(FeatureGroup):
            name = "tournament_mom36"
            columns = ["mom_36m"]
            dependencies = []
            phase = 1
            def compute(self, df):
                p = "adj_closing_price" if "adj_closing_price" in df.columns else "closing_price"
                df["mom_36m"] = df.groupby("stock_code", sort=False)[p].pct_change(756)
                return df

    def chunks(self, start_date: str, end_date: str, target_horizon: int):
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        warmup_days = 1200
        lookahead_days = max(int(target_horizon * 7 / 5) + 20, 50)
        out = []
        for year in range(start_dt.year, end_dt.year + 1):
            trim_start = max(start_dt, datetime(year, 1, 1))
            trim_end = min(end_dt, datetime(year, 12, 31))
            if trim_start > trim_end:
                continue
            out.append({
                "year": year,
                "core_start": (trim_start - timedelta(days=warmup_days)).strftime("%Y%m%d"),
                "core_end": (trim_end + timedelta(days=lookahead_days)).strftime("%Y%m%d"),
                "trim_start": trim_start.strftime("%Y%m%d"),
                "trim_end": trim_end.strftime("%Y%m%d"),
            })
        return out

    def hard_filters(self, df, min_price=2000, liquidity_drop_pct=0.20):
        mask = pd.to_numeric(df["closing_price"], errors="coerce") >= min_price
        if "avg_value_20d" in df.columns:
            cut = df.groupby("date")["avg_value_20d"].transform(lambda s: s.quantile(liquidity_drop_pct))
            mask &= df["avg_value_20d"] >= cut
        if "roe" in df.columns:
            mask &= df["roe"].isna() | (df["roe"].abs() <= 3.0)
        return df.loc[mask]

    def portable_market(self, start_date: str, end_date: str, target_horizon: int):
        with self._connect() as con:
            x = pd.read_sql_query("""
                SELECT dp.stock_code, dp.date, dp.market_cap,
                       COALESCE(ap.adj_closing_price, dp.closing_price) AS px
                FROM daily_prices dp
                LEFT JOIN adj_daily_prices ap
                  ON ap.stock_code=dp.stock_code AND ap.date=dp.date
                WHERE dp.date BETWEEN ? AND ?
                  AND dp.market_type IN ('kospi','kosdaq')
                  AND dp.market_cap >= ? AND dp.volume > 0 AND dp.closing_price > 0
                ORDER BY dp.stock_code, dp.date
            """, con, params=[start_date, end_date, cfg.min_market_cap])
        if x.empty:
            cols = ["date","market_regime_120d","market_regime_20d","market_ret_1d"]
            cols += [f"market_forward_return_{h}d" for h in sorted({21,42,63,target_horizon})]
            return pd.DataFrame(columns=cols)
        x["px"] = pd.to_numeric(x["px"], errors="coerce")
        x["market_cap"] = pd.to_numeric(x["market_cap"], errors="coerce")
        x["ret"] = x.groupby("stock_code", sort=False)["px"].pct_change()
        x["lag_mcap"] = x.groupby("stock_code", sort=False)["market_cap"].shift(1)
        x = x[np.isfinite(x["ret"]) & np.isfinite(x["lag_mcap"]) & (x["lag_mcap"] > 0)]
        rows = []
        for d, g in x.groupby("date", sort=True):
            rows.append((d, np.average(g["ret"], weights=g["lag_mcap"])))
        daily = pd.DataFrame(rows, columns=["date", "market_ret_1d"])
        daily["market_ret_1d"] = daily["market_ret_1d"].clip(-0.35, 0.35).fillna(0.0)
        daily["level"] = (1.0 + daily["market_ret_1d"]).cumprod() * 1000.0
        daily["market_regime_120d"] = daily["level"] / daily["level"].rolling(120, min_periods=60).mean() - 1
        daily["market_regime_20d"] = daily["level"] / daily["level"].rolling(20, min_periods=10).mean() - 1
        hs = sorted({21, 42, 63, target_horizon})
        for h in hs:
            daily[f"market_forward_return_{h}d"] = daily["level"].shift(-h) / daily["level"] - 1
        cols = ["date","market_regime_120d","market_regime_20d","market_ret_1d"]
        cols += [f"market_forward_return_{h}d" for h in hs]
        return daily[cols]

    FeatureEngineer._build_year_chunks = chunks
    FeatureEngineer._apply_hard_universe_filters = hard_filters
    FeatureEngineer._load_market_regime = portable_market
    return FeatureEngineer


def add_q5_proxy_fields(panel: pd.DataFrame, db: Path) -> pd.DataFrame:
    sql = """
    WITH bs AS (
      SELECT period_id,
        MAX(CASE WHEN item_code_normalized='ifrs-full_Assets' THEN amount_current END) AS assets,
        MAX(CASE WHEN item_code_normalized='ifrs-full_Equity' THEN amount_current END) AS equity,
        MAX(CASE WHEN item_code_normalized='ifrs-full_Liabilities' THEN amount_current END) AS liabilities,
        MAX(CASE WHEN item_code_normalized='ifrs-full_CashFlowsFromUsedInOperatingActivities' THEN amount_current END) AS ocf
      FROM financial_items_bs_cf
      GROUP BY period_id
    )
    SELECT fp.stock_code, REPLACE(fp.available_date,'-','') AS available_date,
           fp.fiscal_date, fp.fiscal_month, bs.assets, bs.equity, bs.liabilities, bs.ocf
    FROM financial_periods fp JOIN bs ON bs.period_id=fp.id
    WHERE fp.consolidation_type='연결'
    ORDER BY fp.stock_code, fp.available_date
    """
    with sqlite3.connect(db) as con:
        f = pd.read_sql_query(sql, con)
    if f.empty:
        raise RuntimeError("q5 proxy: no financial rows")
    f["fiscal_dt"] = pd.to_datetime(f["fiscal_date"], errors="coerce")
    f["fiscal_month"] = pd.to_numeric(f["fiscal_month"], errors="coerce").fillna(12).astype(int)
    f["is_annual"] = f["fiscal_dt"].dt.month.eq(f["fiscal_month"])
    f = f[f["is_annual"]].copy()
    for c in ["assets","equity","liabilities","ocf"]:
        f[c] = pd.to_numeric(f[c], errors="coerce")
    f = f.sort_values(["stock_code","fiscal_dt","available_date"]).drop_duplicates(
        ["stock_code","fiscal_date"], keep="last"
    )
    f["lag_assets"] = f.groupby("stock_code")["assets"].shift(1)
    f["q5_ia"] = f["assets"] / f["lag_assets"].replace(0,np.nan) - 1.0
    f = f[["stock_code","available_date","assets","equity","liabilities","ocf","q5_ia"]]
    f["available_dt"] = pd.to_datetime(f["available_date"], format="%Y%m%d", errors="coerce")

    p = panel.copy()
    p["date_dt"] = pd.to_datetime(p["date"], format="%Y%m%d")
    p = pd.merge_asof(
        p.sort_values(["date_dt","stock_code"]),
        f.dropna(subset=["available_dt"]).sort_values(["available_dt","stock_code"]),
        left_on="date_dt", right_on="available_dt", by="stock_code", direction="backward"
    )
    p["q5_logq_proxy"] = np.log(((p["market_cap"] + p["liabilities"].clip(lower=0)) /
                                    p["assets"].replace(0,np.nan)).clip(lower=1e-8))
    p["q5_cop"] = p["ocf"] / p["assets"].replace(0,np.nan)
    p = p.sort_values(["stock_code","date"])
    p["q5_droe"] = p["roe"] - p.groupby("stock_code")["roe"].shift(252)
    return p.drop(columns=["date_dt","available_dt","available_date"], errors="ignore")


def common_universe(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x = x[x["sector"].fillna("").ne("UNMAPPED_SECTOR")]
    pat = "|".join(FINANCIAL_KEYWORDS)
    x = x[~x["sector"].fillna("").str.contains(pat, regex=True)]
    if "equity" in x.columns:
        x = x[pd.to_numeric(x["equity"], errors="coerce") > 0]
    return x


def global_rebalance_dates(df: pd.DataFrame, cfg: Config):
    dates = sorted(d for d in df["date"].unique() if cfg.test_start <= d <= cfg.end)
    return dates[::cfg.horizon]


def rerank_market(frame: pd.DataFrame, raw_score: pd.Series):
    f = frame.copy()
    f["raw_score"] = raw_score
    if f["market_type"].nunique() > 1:
        f["score"] = f.groupby("market_type")["raw_score"].rank(method="average", pct=True)
    else:
        f["score"] = f["raw_score"].rank(method="average", pct=True)
    f["rank_pos"] = f["score"].rank(ascending=False, method="first")
    return f


def q5_proxy_score(day: pd.DataFrame):
    eg = pd.concat([
        day["q5_logq_proxy"].rank(pct=True),
        day["q5_cop"].rank(pct=True),
        day["q5_droe"].rank(pct=True),
    ], axis=1).mean(axis=1)
    return pd.concat([
        day["roe"].rank(pct=True),
        eg,
        (-day["q5_ia"]).rank(pct=True),
    ], axis=1).mean(axis=1)


def lowvol_trend_score(day: pd.DataFrame):
    parts = []
    for col, sign in LOWVOL_TREND:
        parts.append((sign * pd.to_numeric(day[col], errors="coerce")).rank(pct=True))
    return pd.concat(parts, axis=1).mean(axis=1)


def train_ml_signals(df: pd.DataFrame, features: list[str], cfg: Config, name: str, rebal_dates: list[str]):
    from ml.models.lgbm import LGBMRanker
    missing = [c for c in features if c not in df.columns]
    if missing:
        raise KeyError(f"{name}: missing features {missing}")
    all_dates = sorted(df["date"].unique())
    out = []
    for test_year in sorted({int(d[:4]) for d in rebal_dates}):
        year_dates = [d for d in rebal_dates if int(d[:4]) == test_year]
        train_start = f"{test_year-cfg.train_years}0101"
        first_test = min(year_dates)
        before = [d for d in all_dates if d < first_test]
        embargo_cut = before[-cfg.embargo] if len(before) >= cfg.embargo else first_test
        train = df[(df["date"] >= train_start) & (df["date"] < embargo_cut)].copy()
        if train.empty:
            print(f"[{name}] skip {test_year}: no training rows", flush=True)
            continue
        years = sorted(train["date"].str[:4].unique())
        val_year = years[-1]
        sub = train[train["date"].str[:4] != val_year].copy()
        val = train[train["date"].str[:4] == val_year].copy()
        if len(sub) < 10_000 or len(val) < 2_000:
            sub, val = train, None
        target = f"target_residual_rank_{cfg.horizon}d"
        model = LGBMRanker(features, target_col=target, time_decay=0.2, patience=300)
        params = model.BEST_PARAMS.copy()
        params.update({"learning_rate":0.005, "n_estimators":3000, "seed":42})
        print(f"[{name}] train {test_year}: rows={len(sub):,} val={0 if val is None else len(val):,}", flush=True)
        model.train(sub, val, params=params)
        for d in year_dates:
            day = df[df["date"].eq(d)].copy()
            if day.empty:
                continue
            pred = pd.Series(model.predict(day, swa=True), index=day.index)
            r = rerank_market(day, pred)
            r["strategy"] = name
            out.append(r[["date","stock_code","name","sector","market_type","market_cap","score","rank_pos"]])
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def static_signals(df: pd.DataFrame, cfg: Config, rebal_dates: list[str], kind: str):
    out = []
    for d in rebal_dates:
        day = df[df["date"].eq(d)].copy()
        if day.empty:
            continue
        score = q5_proxy_score(day) if kind == "q5_proxy" else lowvol_trend_score(day)
        r = rerank_market(day, score)
        r["strategy"] = kind
        out.append(r[["date","stock_code","name","sector","market_type","market_cap","score","rank_pos"]])
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def choose_holdings(day: pd.DataFrame, previous: set[str], cfg: Config):
    d = day.dropna(subset=["rank_pos"]).sort_values("rank_pos")
    protected = list(d[d["stock_code"].isin(previous) & (d["rank_pos"] <= cfg.hold_rank)]["stock_code"])
    chosen = protected[:cfg.top_n]
    for code in d[(~d["stock_code"].isin(chosen)) & (d["rank_pos"] <= cfg.buy_rank)]["stock_code"]:
        if len(chosen) >= cfg.top_n:
            break
        chosen.append(code)
    if len(chosen) < cfg.top_n:
        for code in d[(~d["stock_code"].isin(chosen)) & (d["rank_pos"] <= cfg.hold_rank)]["stock_code"]:
            if len(chosen) >= cfg.top_n:
                break
            chosen.append(code)
    return set(chosen)


def load_prices(db: Path, codes: list[str], start: str, end: str):
    frames = []
    with sqlite3.connect(db) as con:
        for i in range(0, len(codes), 500):
            chunk = codes[i:i+500]
            qs = ",".join("?" for _ in chunk)
            frames.append(pd.read_sql_query(f"""
              SELECT dp.stock_code, dp.date, dp.value,
                     COALESCE(ap.adj_closing_price, dp.closing_price) AS px
              FROM daily_prices dp LEFT JOIN adj_daily_prices ap
                ON ap.stock_code=dp.stock_code AND ap.date=dp.date
              WHERE dp.stock_code IN ({qs}) AND dp.date BETWEEN ? AND ?
              ORDER BY dp.date, dp.stock_code
            """, con, params=chunk+[start,end]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def simulate_weights(events, db: Path, cfg: Config):
    codes = sorted(set().union(*[set(w.index) for _,w,_ in events])) if events else []
    px = load_prices(db, codes, cfg.test_start, cfg.end)
    if px.empty:
        raise RuntimeError("simulator: no price rows")
    raw = px.pivot(index="date", columns="stock_code", values="px").sort_index()
    value = px.pivot(index="date", columns="stock_code", values="value").reindex(raw.index)
    tradable = value.fillna(0).gt(0)
    mark = raw.ffill()
    dates = list(mark.index)
    by_exec = {}
    for signal_date, weights, ranks in events:
        possible = [d for d in dates if d > signal_date]
        if possible:
            by_exec.setdefault(possible[0], []).append((signal_date, weights, ranks))

    cash = cfg.initial_capital
    pos = {}
    tx = []
    episodes = {}
    ledger = []
    eq = []

    def equity(d):
        return cash + sum(sh * float(mark.at[d,c]) for c,sh in pos.items()
                          if c in mark.columns and pd.notna(mark.at[d,c]))

    def new_ep(c, signal, d):
        return {"stock_code":c,"entry_signal_date":signal,"entry_date":d,
                "buy_notional":0.0,"buy_cost":0.0,"shares_bought":0,
                "sell_notional":0.0,"sell_cost":0.0,"shares_sold":0}

    def close_ep(ep, signal, d):
        buy = ep["buy_notional"] + ep["buy_cost"]
        sell = ep["sell_notional"] - ep["sell_cost"]
        return {**ep,
                "entry_price_vwap":ep["buy_notional"]/ep["shares_bought"] if ep["shares_bought"] else np.nan,
                "exit_signal_date":signal,"exit_date":d,
                "exit_price_vwap":ep["sell_notional"]/ep["shares_sold"] if ep["shares_sold"] else np.nan,
                "holding_days":(pd.to_datetime(d)-pd.to_datetime(ep["entry_date"])).days,
                "net_entry_cash":buy,"net_exit_cash":sell,
                "net_pnl":sell-buy,"net_return":sell/buy-1 if buy>0 else np.nan}

    for d in dates:
        for signal, weights, ranks in by_exec.get(d, []):
            eq0 = equity(d)
            desired = {}
            for c,w in weights.items():
                if c in raw.columns and c in tradable.columns and bool(tradable.at[d,c]) and pd.notna(raw.at[d,c]) and raw.at[d,c] > 0:
                    desired[c] = int(math.floor(eq0*float(w)/float(raw.at[d,c])))
                elif c in pos:
                    desired[c] = pos[c]
            allc = set(pos) | set(desired)
            for c in sorted(allc):
                old,new = int(pos.get(c,0)),int(desired.get(c,0))
                if new >= old:
                    continue
                if c not in tradable.columns or not bool(tradable.at[d,c]):
                    continue
                q=old-new; p=float(raw.at[d,c]); gross=q*p; cost=gross*cfg.sell_cost
                cash += gross-cost
                if new:
                    pos[c]=new
                else:
                    pos.pop(c,None)
                tx.append({"signal_date":signal,"execution_date":d,"stock_code":c,"side":"SELL","shares":q,"price":p,"gross_notional":gross,"cost":cost,"rank_pos":float(ranks.get(c,np.nan)) if ranks is not None else np.nan})
                if c in episodes:
                    ep=episodes[c]; ep["sell_notional"]+=gross; ep["sell_cost"]+=cost; ep["shares_sold"]+=q
                    if new==0:
                        ledger.append(close_ep(ep,signal,d)); episodes.pop(c,None)
            for c in sorted(allc):
                old,new=int(pos.get(c,0)),int(desired.get(c,0))
                if new<=old:
                    continue
                q=new-old; p=float(raw.at[d,c]); q=min(q,int(math.floor(cash/(p*(1+cfg.buy_cost)))))
                if q<=0:
                    continue
                gross=q*p; cost=gross*cfg.buy_cost; cash-=gross+cost; pos[c]=old+q
                tx.append({"signal_date":signal,"execution_date":d,"stock_code":c,"side":"BUY","shares":q,"price":p,"gross_notional":gross,"cost":cost,"rank_pos":float(ranks.get(c,np.nan)) if ranks is not None else np.nan})
                if old==0 or c not in episodes:
                    episodes[c]=new_ep(c,signal,d)
                ep=episodes[c]; ep["buy_notional"]+=gross; ep["buy_cost"]+=cost; ep["shares_bought"]+=q
        eq.append({"date":d,"equity":equity(d),"cash":cash,"n_positions":len(pos)})

    last=dates[-1]
    for c,sh in list(pos.items()):
        if c not in mark.columns or pd.isna(mark.at[last,c]):
            continue
        p=float(mark.at[last,c]); gross=sh*p; cost=gross*cfg.sell_cost; cash+=gross-cost
        tx.append({"signal_date":cfg.end,"execution_date":last,"stock_code":c,"side":"SELL_END","shares":sh,"price":p,"gross_notional":gross,"cost":cost,"rank_pos":np.nan})
        if c in episodes:
            ep=episodes[c]; ep["sell_notional"]+=gross; ep["sell_cost"]+=cost; ep["shares_sold"]+=sh
            ledger.append(close_ep(ep,cfg.end,last))
    if eq:
        eq[-1]={"date":last,"equity":cash,"cash":cash,"n_positions":0}
    return pd.DataFrame(tx), pd.DataFrame(ledger), pd.DataFrame(eq)


def events_from_signals(sig: pd.DataFrame, cfg: Config):
    events=[]; prev=set()
    for d in sorted(sig["date"].unique()):
        day=sig[sig["date"].eq(d)]
        target=choose_holdings(day,prev,cfg)
        if target:
            w=pd.Series(1/len(target),index=sorted(target))
            ranks=day.set_index("stock_code")["rank_pos"]
            events.append((d,w,ranks)); prev=target
    return events


def cap_events(panel: pd.DataFrame, rebal_dates: list[str]):
    events=[]
    for d in rebal_dates:
        day=panel[panel["date"].eq(d)].dropna(subset=["market_cap"])
        w=day.set_index("stock_code")["market_cap"].astype(float)
        w=w[w>0]
        if len(w):
            events.append((d,w/w.sum(),None))
    return events


def summarize(eq: pd.DataFrame, tx: pd.DataFrame, ledger: pd.DataFrame, cfg: Config):
    if eq.empty:
        return {}
    e=eq.copy(); e["dt"]=pd.to_datetime(e["date"]); e=e.sort_values("dt"); e["ret"]=e["equity"].pct_change().fillna(0)
    yrs=max((e["dt"].iloc[-1]-e["dt"].iloc[0]).days/365.25,1/365.25)
    total=e["equity"].iloc[-1]/cfg.initial_capital-1
    cagr=(1+total)**(1/yrs)-1 if total>-1 else -1
    sd=e["ret"].std(ddof=1); sharpe=np.sqrt(252)*e["ret"].mean()/sd if sd and np.isfinite(sd) else np.nan
    dd=e["equity"]/e["equity"].cummax()-1; mdd=dd.min(); calmar=cagr/abs(mdd) if mdd<0 else np.nan
    win=float((ledger["net_pnl"]>0).mean()) if not ledger.empty else np.nan
    return {"total_return":float(total),"cagr":float(cagr),"sharpe":float(sharpe),"max_drawdown":float(mdd),"calmar":float(calmar),"win_rate_positions":win,
            "transaction_cost_krw":float(tx["cost"].sum()) if not tx.empty else 0.0,"gross_traded_krw":float(tx["gross_notional"].sum()) if not tx.empty else 0.0,
            "closed_positions":int(len(ledger)),"end_equity":float(e["equity"].iloc[-1])}


def save_result(root: Path, name: str, sig: pd.DataFrame, events, db: Path, cfg: Config):
    d=root/name; d.mkdir(parents=True,exist_ok=True)
    sig.to_csv(d/"signals.csv",index=False,encoding="utf-8-sig")
    tx,ledger,eq=simulate_weights(events,db,cfg)
    tx.to_csv(d/"transactions.csv",index=False,encoding="utf-8-sig")
    ledger.to_csv(d/"position_ledger.csv",index=False,encoding="utf-8-sig")
    eq.to_csv(d/"equity_curve.csv",index=False,encoding="utf-8-sig")
    sm=summarize(eq,tx,ledger,cfg)
    (d/"summary.json").write_text(json.dumps(sm,ensure_ascii=False,indent=2),encoding="utf-8")
    return sm


def subperiod_metric(eq_file: Path, start: str, end: str):
    e=pd.read_csv(eq_file,dtype={"date":str}); e=e[(e.date>=start)&(e.date<=end)].copy()
    if len(e)<2:
        return {"return":np.nan,"sharpe":np.nan,"mdd":np.nan}
    r=e.equity.pct_change().fillna(0); total=e.equity.iloc[-1]/e.equity.iloc[0]-1; sd=r.std(ddof=1)
    shp=np.sqrt(252)*r.mean()/sd if sd and np.isfinite(sd) else np.nan
    mdd=(e.equity/e.equity.cummax()-1).min()
    return {"return":float(total),"sharpe":float(shp),"mdd":float(mdd)}


def main():
    a=parse_args(); alphakrx=Path(a.alphakrx_root).resolve(); db=Path(a.db).resolve(); out=Path(a.output).resolve(); out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(alphakrx))
    cfg=Config(a.feature_start,a.test_start,a.end)
    FeatureEngineer=register_mom36_and_patch_engine(alphakrx,db,cfg)
    print("[panel] build AlphaKRX feature panel on public marcap+DART", flush=True)
    fe=FeatureEngineer(str(db))
    panel=fe.prepare_ml_data(start_date=cfg.feature_start,end_date=cfg.end,target_horizon=cfg.horizon,min_market_cap=cfg.min_market_cap,use_cache=False,n_workers=1)
    if panel.empty:
        raise RuntimeError("empty feature panel")
    panel=add_q5_proxy_fields(panel,db)
    panel=common_universe(panel).sort_values(["date","stock_code"]).reset_index(drop=True)
    panel.to_parquet(out/"common_panel.parquet",index=False)
    rebal=global_rebalance_dates(panel,cfg)
    if len(rebal)<4:
        raise RuntimeError(f"too few rebalance dates: {len(rebal)}")
    print(f"[panel] rows={len(panel):,} names={panel.stock_code.nunique():,} rebalances={len(rebal)}",flush=True)

    full=train_ml_signals(panel,PORTABLE_FULL_FEATURES,cfg,"portable_full_ml",rebal)
    core=train_ml_signals(panel,KR_CORE_PORTABLE,cfg,"kr_core_portable",rebal)
    q5=static_signals(panel,cfg,rebal,"q5_proxy")
    lvt=static_signals(panel,cfg,rebal,"lowvol_trend")

    comparison=[]
    for name,sig in [("portable_full_ml",full),("kr_core_portable",core),("q5_proxy",q5),("lowvol_trend",lvt)]:
        sm=save_result(out,name,sig,events_from_signals(sig,cfg),db,cfg); comparison.append({"strategy":name,**sm})
    bench_sig=pd.concat([panel[panel.date.eq(d)][["date","stock_code","market_cap"]] for d in rebal],ignore_index=True)
    sm=save_result(out,"universe_cap",bench_sig,cap_events(panel,rebal),db,cfg); comparison.append({"strategy":"universe_cap",**sm})

    comp=pd.DataFrame(comparison)
    b=comp[comp.strategy.eq("universe_cap")].iloc[0]
    comp["cagr_alpha_vs_cap"]=comp.cagr-b.cagr
    comp["sharpe_delta_vs_cap"]=comp.sharpe-b.sharpe
    comp=comp.sort_values(["sharpe","calmar"],ascending=False,na_position="last")
    comp.to_csv(out/"comparison.csv",index=False,encoding="utf-8-sig")

    subs={}
    for name in comp.strategy:
        eqf=out/name/"equity_curve.csv"
        subs[name]={
            "2018_2021":subperiod_metric(eqf,"20180101","20211231"),
            "2022_2026":subperiod_metric(eqf,"20220101","20261231"),
        }
    manifest={
      "config":asdict(cfg),
      "data_source":"FinanceData/marcap parquet + AlphaKRX bundled DART bulk files",
      "alphakrx_commit":"e773d4243b7a644dd0c525daccebdf062bc389a1",
      "methodology_label":"retrospective/pseudo-OOS for KR-CORE; not untouched forward OOS",
      "portable_full_note":"not identical to published AlphaKRX Full ML; macro/VKOSPI interactions excluded and market residual uses same-universe cap-weight return",
      "q5_note":"q5-inspired long-only proxy, not exact HMXZ/q5 replication",
      "kr_core_features":KR_CORE_PORTABLE,
      "portable_full_features":PORTABLE_FULL_FEATURES,
      "subperiods":subs,
      "winner_rule":"after-cost Sharpe first, then Calmar/MDD, CAGR alpha, subperiod stability, turnover/cost",
    }
    (out/"run_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# Portable Korean Strategy Tournament","",
           "This is a retrospective/pseudo-OOS tournament for KR-CORE, not genuine untouched forward OOS.","",
           comp.to_markdown(index=False),"",
           f"Risk-adjusted leader: **{comp.iloc[0].strategy}**","",
           "`portable_full_ml` is not the published AlphaKRX Full ML because unavailable macro/VKOSPI inputs are deliberately excluded.",
           "`q5_proxy` is a long-only q5-inspired proxy, not an exact q5 factor replication."]
    (out/"winner_report.md").write_text("\n".join(lines),encoding="utf-8")
    print(comp.to_string(index=False),flush=True)


if __name__=="__main__":
    main()
