"""
IV 引擎 — 隐含波动率获取与分位计算
==================================
数据源: 东方财富 API（通过 AKShare option_value_analysis_em）
"""

import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


def fetch_iv_chain() -> pd.DataFrame:
    """
    获取当日所有 ETF 期权的 IV 数据。

    Returns:
        DataFrame with columns:
        [期权代码, 期权名称, 最新价, 时间价值, 内在价值,
         隐含波动率, 理论价格, 标的名称, 标的最新价,
         标的近一年波动率, 到期日]
    """
    from akshare.option.option_value_analysis_em import option_value_analysis_em
    return option_value_analysis_em()


def filter_510500(df: pd.DataFrame) -> pd.DataFrame:
    """从期权链中筛选 510500 ETF 期权"""
    mask = df["期权名称"].astype(str).str.contains("500")
    return df[mask].copy()


def get_atm_iv(df: pd.DataFrame,
               underlying_price: float,
               min_dte: int = 21,
               max_dte: int = 60) -> dict:
    """
    取近月 ATM IV。

    Args:
        df: 510500 期权链
        underlying_price: 标的最新价
        min_dte: 最少剩余日（排除近到期 Gamma 风险）
        max_dte: 最多剩余日（近月范围）

    Returns:
        {
            "iv_call": float,
            "iv_put": float,
            "iv_avg": float,
            "strike": float,
            "dte": int,
            "call_code": str,
            "put_code": str,
        }
    """
    # 筛近月
    d = df[(df["剩余日"] >= min_dte) & (df["剩余日"] <= max_dte)].copy()
    if d.empty:
        d = df[df["剩余日"] >= min_dte].copy()
    if d.empty:
        return None

    # 找最接近ATM的两档
    d["dist"] = (d["行权价"] - underlying_price).abs()
    d = d.sort_values("dist")

    # 分离 Call/Put
    calls = d[d["期权名称"].str.contains("购")]
    puts = d[d["期权名称"].str.contains("沽")]

    if calls.empty or puts.empty:
        return None

    atm_call = calls.iloc[0]
    atm_put = puts.iloc[0]

    return {
        "iv_call": float(atm_call["隐含波动率"]) / 100,
        "iv_put": float(atm_put["隐含波动率"]) / 100,
        "iv_avg": (float(atm_call["隐含波动率"]) + float(atm_put["隐含波动率"])) / 200,
        "strike": float(atm_call["行权价"]),
        "dte": int(atm_call["剩余日"]),
        "call_code": str(atm_call["期权代码"]),
        "put_code": str(atm_put["期权代码"]),
    }


class IVHistory:
    """IV 历史序列管理"""

    def __init__(self, window: int = 252):
        self.window = window
        self.history: list[float] = []

    def add(self, iv: float):
        self.history.append(iv)
        if len(self.history) > self.window:
            self.history = self.history[-self.window:]

    def percentile(self, iv: float) -> float:
        """计算当前 IV 在历史中的分位数（0-100）"""
        if len(self.history) < 20:
            return 50.0  # 数据不足时默认中位
        return (sum(1 for h in self.history if h < iv) / len(self.history)) * 100

    def classify(self, iv: float,
                 high_pct: float = 70.0,
                 low_pct: float = 30.0) -> str:
        """
        IV 分档: HIGH / MID / LOW

        IV ≥ high_pct 分位 → HIGH（情绪贵）
        IV ≤ low_pct 分位 → LOW（情绪便宜）
        否则 → MID
        """
        pct = self.percentile(iv)
        if pct >= high_pct:
            return "HIGH"
        if pct <= low_pct:
            return "LOW"
        return "MID"

    def current_quantile(self, iv: float) -> dict:
        return {
            "iv": round(iv * 100, 2),
            "percentile": round(self.percentile(iv), 1),
            "level": self.classify(iv),
            "history_len": len(self.history),
        }
