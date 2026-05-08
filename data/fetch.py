"""
数据获取 — 标的日线与期权 IV
============================
"""

import pandas as pd
import numpy as np
import warnings
import time

warnings.filterwarnings("ignore")


def fetch_index_daily(symbol: str = "sh000905",
                      lookback: int = 250) -> pd.DataFrame:
    """
    获取指数日线数据。

    Args:
        symbol: "sh000905" (中证500), "sh000016" (上证50), etc.
        lookback: 最近多少交易日

    Returns:
        DataFrame [date, open, high, low, close] 按日期升序
    """
    from akshare import stock_zh_index_daily
    df = stock_zh_index_daily(symbol=symbol)
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "open", "high", "low", "close"]]
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(lookback).reset_index(drop=True)


def fetch_etf_daily(symbol: str = "510500",
                    lookback: int = 250) -> pd.DataFrame:
    """
    获取 ETF 日线数据。

    Args:
        symbol: "510500", "510050", etc.

    Returns:
        DataFrame [date, open, high, low, close]
    """
    from akshare import fund_etf_hist_em
    df = fund_etf_hist_em(symbol=symbol, period="daily", adjust="qfq")
    df["date"] = pd.to_datetime(df["日期"])
    df = df.rename(columns={"开盘": "open", "最高": "high",
                             "最低": "low", "收盘": "close"})
    df = df[["date", "open", "high", "low", "close"]]
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(lookback).reset_index(drop=True)


def fetch_option_chain_510500() -> pd.DataFrame:
    """
    获取 510500 ETF 期权链（含 IV）。

    Returns:
        DataFrame
    """
    try:
        from strategy.iv_engine import fetch_iv_chain, filter_510500
        df = fetch_iv_chain()
        return filter_510500(df)
    except Exception as e:
        # fallback: 如果东方财富 API 限流，返回空 DataFrame
        print(f"[WARN] 期权链获取失败: {e}")
        return pd.DataFrame()


def get_underlying_price(df_etf: pd.DataFrame) -> float:
    """获取标的收盘价"""
    if df_etf.empty:
        return 0.0
    return float(df_etf["close"].iloc[-1])


def compute_atr_pct_from_etf(df_etf: pd.DataFrame, period: int = 5) -> float:
    """从 ETF 日线计算 ATR%"""
    if len(df_etf) < period + 1:
        return 0.02
    closes = df_etf["close"].values[-period-1:]
    highs = df_etf["high"].values[-period:]
    lows = df_etf["low"].values[-period:]
    tr_pcts = []
    for i in range(len(highs)):
        h, l, pc = highs[i], lows[i], closes[i]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_pcts.append(tr / pc)
    return float(np.mean(tr_pcts))
