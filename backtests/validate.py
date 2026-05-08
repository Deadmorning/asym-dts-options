"""
回测验证 — H 信号历史表现分析
===============================
不依赖实时期权数据，只用指数日线回测信号质量。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
from datetime import timedelta

from strategy.signals import compute_wts, compute_dts, h_state_machine
from data.fetch import fetch_index_daily, fetch_etf_daily


def backtest_h_etf(symbol_index: str = "sh000905",
                   symbol_etf: str = "510500",
                   start: str = "2024-01-02",
                   end: str = None) -> pd.DataFrame:
    """
    H 策略在 ETF 上的日频回测。

    模拟: 14:55 算信号 → 次日开盘执行
    不能做空，二元方向（全仓/空仓）。

    Returns:
        DataFrame with columns:
        [date, target, position, etf_price, etf_return,
         strategy_return, equity_curve, signal_branch]
    """
    df_index = fetch_index_daily(symbol=symbol_index, lookback=500)
    df_etf = fetch_etf_daily(symbol=symbol_etf, lookback=500)

    # 对齐日期
    df_index = df_index[df_index["date"] >= start]
    if end:
        df_index = df_index[df_index["date"] <= end]
    df_index = df_index.reset_index(drop=True)

    if df_index.empty:
        return pd.DataFrame()

    # WTS 预计算（加速）
    first_date = df_index["date"].iloc[0]
    wts_cache = {}
    last_computed_week = None

    results = []
    position = 0
    prev_dts = 1

    for i in range(len(df_index)):
        today = df_index["date"].iloc[i]
        current_week = today.strftime("%Y-%W")

        # WTS
        if current_week != last_computed_week:
            days_since_friday = (today.weekday() + 2) % 7
            if days_since_friday == 0:
                days_since_friday = 7
            last_friday = today - timedelta(days=days_since_friday)

            cutoff = max(last_friday, first_date)
            hist = df_index[df_index["date"] <= cutoff].copy()
            wts_cache = compute_wts(hist)
            last_computed_week = current_week

        if not wts_cache:
            continue

        if current_week in wts_cache:
            wts_state = wts_cache[current_week]
        else:
            wts_state = list(wts_cache.values())[-1]

        wts_signal, prev_class, curr_class = wts_state

        # last_wts
        all_weeks = sorted(wts_cache.keys())
        try:
            idx = all_weeks.index(current_week)
        except ValueError:
            idx = len(all_weeks) - 1
        prev_week = all_weeks[idx - 1] if idx > 0 else all_weeks[0]
        last_wts = wts_cache.get(prev_week, (1, "FLAT", "FLAT"))[0]

        # DTS
        if i >= 2:
            dts_yesterday = compute_dts(df_index.iloc[i-2], df_index.iloc[i-1])
            dts_today = compute_dts(df_index.iloc[i-1], df_index.iloc[i])
        else:
            dts_yesterday = 1
            dts_today = 1
        dts_decision = dts_yesterday if dts_yesterday is not None else prev_dts
        prev_dts = dts_today if dts_today is not None else prev_dts

        # 状态机
        target = h_state_machine(wts_signal, last_wts, prev_class, curr_class, dts_decision)

        # ETF 价格
        etf_row = df_etf[df_etf["date"] == today]
        if etf_row.empty:
            etf_price = df_etf[df_etf["date"] <= today]["close"].iloc[-1] if len(df_etf[df_etf["date"] <= today]) > 0 else 0
        else:
            etf_price = float(etf_row["close"].iloc[0])

        results.append({
            "date": today,
            "target": target,
            "wts_signal": wts_signal,
            "prev_class": prev_class,
            "curr_class": curr_class,
            "last_wts": last_wts,
            "dts_decision": dts_decision,
            "etf_price": etf_price,
            "week": current_week,
        })

    df = pd.DataFrame(results)
    if df.empty:
        return df

    # 模拟交易: T+1，次日开盘成交
    df["position"] = 0
    df["signal_date"] = df["date"]

    for i in range(1, len(df)):
        df.loc[i, "position"] = df.loc[i-1, "target"]

    # 收益
    df["etf_return"] = df["etf_price"].pct_change()
    df["strategy_return"] = df["position"] * df["etf_return"]
    df["equity_curve"] = (1 + df["strategy_return"]).cumprod()

    return df


def summarize_backtest(df: pd.DataFrame) -> dict:
    """回测汇总统计"""
    if df.empty:
        return {}

    bh_return = (df["etf_price"].iloc[-1] / df["etf_price"].iloc[0] - 1) * 100
    strat_return = (df["equity_curve"].iloc[-1] - 1) * 100

    # 交易统计
    trades = []
    in_position = False
    entry_price = 0
    for i in range(1, len(df)):
        if df["position"].iloc[i] == 1 and not in_position:
            in_position = True
            entry_price = df["etf_price"].iloc[i]
        elif df["position"].iloc[i] == 0 and in_position:
            in_position = False
            trades.append({
                "entry": entry_price,
                "exit": df["etf_price"].iloc[i],
                "pnl_pct": (df["etf_price"].iloc[i] / entry_price - 1) * 100,
            })

    win_trades = [t for t in trades if t["pnl_pct"] > 0]
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0

    # 信号统计
    full_pct = df["target"].mean() * 100

    return {
        "period": f"{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}",
        "bh_return_pct": round(bh_return, 2),
        "strategy_return_pct": round(strat_return, 2),
        "excess_return_pct": round(strat_return - bh_return, 2),
        "num_trades": len(trades),
        "win_rate_pct": round(win_rate, 1),
        "avg_pnl_pct": round(np.mean([t["pnl_pct"] for t in trades]), 2) if trades else 0,
        "full_pct_of_time": round(full_pct, 1),
        "max_trade_pnl": round(max([t["pnl_pct"] for t in trades]), 2) if trades else 0,
        "min_trade_pnl": round(min([t["pnl_pct"] for t in trades]), 2) if trades else 0,
    }
