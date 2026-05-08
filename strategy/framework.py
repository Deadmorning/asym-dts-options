"""
主框架 — 日频执行器
====================
每天收盘后运行一次，输出次日交易信号。
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

# 添加项目根目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy.signals import run_signal_pipeline
from strategy.iv_engine import get_atm_iv, IVHistory
from strategy.decision_matrix import decide
from data.fetch import (
    fetch_index_daily, fetch_etf_daily,
    fetch_option_chain_510500, get_underlying_price,
    compute_atr_pct_from_etf,
)


def load_iv_history(path: str = "iv_history.json") -> IVHistory:
    """加载 IV 历史序列"""
    ivh = IVHistory(window=252)
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
            for v in data.get("history", []):
                ivh.add(v)
    return ivh


def save_iv_history(ivh: IVHistory, path: str = "iv_history.json"):
    """保存 IV 历史序列"""
    with open(path, "w") as f:
        json.dump({"history": ivh.history, "updated": str(datetime.now())}, f)


def run_daily(symbol_index: str = "sh000905",
              symbol_etf: str = "510500",
              save_history: bool = True,
              history_path: str = "iv_history.json",
              verbose: bool = True) -> dict:
    """
    每日运行一次。

    Returns:
        dict with full signal + decision output
    """
    result = {
        "timestamp": str(datetime.now()),
        "symbol_index": symbol_index,
        "symbol_etf": symbol_etf,
        "status": "ok",
    }

    # ---- Step 1: 数据加载 ----
    if verbose:
        print("[1/5] 加载数据...")
    df_index = fetch_index_daily(symbol=symbol_index)
    df_etf = fetch_etf_daily(symbol=symbol_etf)
    underlying_price = get_underlying_price(df_etf)
    today = df_index["date"].iloc[-1]
    result["date"] = str(today.date())
    result["underlying_price"] = underlying_price

    if verbose:
        print(f"      标的: {symbol_etf} @ {underlying_price}")
        print(f"      日期: {today.date()}")

    # ---- Step 2: H 信号 ----
    if verbose:
        print("[2/5] 计算 H 策略信号...")
    signal_result = run_signal_pipeline(df_index, today)
    if "error" in signal_result:
        result["status"] = "error"
        result["error"] = signal_result["error"]
        return result
    result["signal"] = signal_result

    if verbose:
        print(f"      方向: {'FULL' if signal_result['target']==1 else 'FLAT'}")
        print(f"      分支: {signal_result['branch']}")
        print(f"      WTS翻多周数: {signal_result['weeks_since_flip']}")

    # ---- Step 3: IV ----
    if verbose:
        print("[3/5] 获取 IV 数据...")
    iv_result = None
    try:
        df_opt = fetch_option_chain_510500()
        if not df_opt.empty:
            atm = get_atm_iv(df_opt, underlying_price)
            ivh = load_iv_history(history_path)
            ivh.add(atm["iv_avg"])
            iv_result = ivh.current_quantile(atm["iv_avg"])
            iv_result["dte"] = atm["dte"]
            iv_result["strike"] = atm["strike"]
            if save_history:
                save_iv_history(ivh, history_path)
            if verbose:
                print(f"      IV={atm['iv_avg']*100:.1f}%  "
                      f"分位={iv_result['percentile']:.0f}th  "
                      f"档={iv_result['level']}  "
                      f"DTE={atm['dte']}d")
        else:
            if verbose:
                print("      [WARN] 期权链数据为空，IV fallback=MID")
            iv_result = {"iv": 23.0, "percentile": 50.0, "level": "MID",
                         "dte": 47, "strike": 0}
    except Exception as e:
        if verbose:
            print(f"      [WARN] IV 获取异常: {e}")
        iv_result = {"iv": 23.0, "percentile": 50.0, "level": "MID",
                     "dte": 47, "strike": 0}
    result["iv"] = iv_result

    # ---- Step 4: ATR ----
    if verbose:
        print("[4/5] 计算 ATR...")
    atr_pct = compute_atr_pct_from_etf(df_etf)
    result["atr_pct"] = round(atr_pct * 100, 2)
    if verbose:
        print(f"      ATR% = {atr_pct*100:.2f}%")

    # ---- Step 5: 决策矩阵 ----
    if verbose:
        print("[5/5] 决策矩阵...")
    trade = decide(signal_result, iv_result, underlying_price, atr_pct)
    trade.date = str(today.date())
    result["trade"] = {
        "action": trade.action,
        "direction": trade.direction,
        "iv_level": trade.iv_level,
        "entry_allowed": trade.entry_allowed,
        "description": trade.description,
        "sell_strike": trade.sell_strike,
        "buy_strike": trade.buy_strike,
        "spread_width_pct": trade.spread_width_pct,
        "dte_target": trade.dte_target,
        "conditions": trade.conditions,
        "position_state": getattr(trade, "position_state", ""),
        "stop_loss": getattr(trade, "stop_loss", None),
        "position_advice": getattr(trade, "position_advice", ""),
    }

    if verbose:
        print()
        print("=" * 60)
        print(f"  交易信号: {trade.action}")
        print(f"  入场允许: {'✅' if trade.entry_allowed else '❌'}")
        print(f"  持仓状态: {getattr(trade, 'position_state', '')}")
        if getattr(trade, 'stop_loss', None):
            print(f"  止损价: {trade.stop_loss}")
        print(f"  {trade.description}")
        if getattr(trade, 'position_advice', ''):
            print(f"  {trade.position_advice}")
        print("=" * 60)

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="H+IV 策略日频执行器")
    parser.add_argument("--index", default="sh000905", help="指数代码")
    parser.add_argument("--etf", default="510500", help="ETF代码")
    parser.add_argument("--no-save", action="store_true", help="不保存IV历史")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()

    result = run_daily(
        symbol_index=args.index,
        symbol_etf=args.etf,
        save_history=not args.no_save,
        verbose=not args.json,
    )

    if args.json:
        # 清理不可序列化字段
        if "signal" in result and "wts_history" in result["signal"]:
            del result["signal"]["wts_history"]
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
