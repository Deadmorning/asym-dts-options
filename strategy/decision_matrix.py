"""
决策矩阵 — 四象限期权结构选择
===============================

WTS/DTS → 方向 (FULL / FLAT)
IV 分位  → 表达 (HIGH / MID / LOW)

方向决策和表达决策分层，互不污染。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TradeSignal:
    """单日交易信号"""
    date: str
    direction: str       # "FULL" | "FLAT"
    iv_level: str        # "HIGH" | "MID" | "LOW"
    action: str          # "SELL_PUT_SPREAD" | "SELL_CALL_SPREAD" |
                         # "BUY_CALL" | "WAIT" | "HOLD"
    description: str
    entry_allowed: bool

    # 期权参数
    sell_strike: Optional[float] = None
    buy_strike: Optional[float] = None
    spread_width_pct: Optional[float] = None
    dte_target: Optional[int] = None

    # 入场条件逐项结果
    conditions: dict = field(default_factory=dict)

    # 持仓管理
    hold_advice: str = ""
    stop_loss: Optional[float] = None


def compute_atr_pct(df_close, period: int = 5) -> float:
    """计算 ATR 百分比"""
    import numpy as np
    if len(df_close) < period + 1:
        return 0.02
    highs = df_close[-period:]
    lows = df_close[-period:]
    tr_pct = []
    for i in range(1, len(highs)):
        h, l = max(highs.iloc[i], highs.iloc[i-1]), min(lows.iloc[i], lows.iloc[i-1])
        tr_pct.append(abs(h - l) / max(highs.iloc[i-1], lows.iloc[i-1]))
    return np.mean(tr_pct)


def decide(signal_result: dict,
           iv_result: dict,
           underlying_price: float,
           atr_pct: float = 0.02) -> TradeSignal:
    """
    四象限决策矩阵。

    Args:
        signal_result: run_signal_pipeline() 的返回
        iv_result: get_atm_iv() 的返回
        underlying_price: 标的现价
        atr_pct: ATR 百分比

    Returns:
        TradeSignal
    """
    target = signal_result["target"]
    direction = "FULL" if target == 1 else "FLAT"
    iv_level = iv_result.get("level", "MID") if iv_result else "MID"
    iv_val = iv_result.get("iv", 0) if iv_result else 0
    weeks_since_flip = signal_result.get("weeks_since_flip", 0)
    dte = iv_result.get("dte", 47) if iv_result else 47

    ts = TradeSignal(
        date="",
        direction=direction,
        iv_level=iv_level,
        action="WAIT",
        description="",
        entry_allowed=False,
        dte_target=dte,
    )

    # ============================================================
    # QUADRANT: FULL + IV HIGH → SELL_PUT_SPREAD
    # ============================================================
    if direction == "FULL" and iv_level == "HIGH":
        ts.action = "SELL_PUT_SPREAD"
        otm_dist = atr_pct * 0.8
        ts.sell_strike = round(underlying_price * (1 - otm_dist), 2)
        ts.buy_strike = round(ts.sell_strike * 0.95, 2)
        ts.spread_width_pct = round((ts.sell_strike - ts.buy_strike) / ts.sell_strike * 100, 1)

        cond1 = weeks_since_flip <= 2
        cond2 = iv_val >= 50
        cond3 = ts.sell_strike / underlying_price <= 0.92

        ts.conditions = {
            "WTS翻多≤2周": (cond1, f"当前{weeks_since_flip}周"),
            "IV≥50th分位": (cond2, f"当前{iv_val}th"),
            "Put strike安全距离(≤0.92)": (cond3, f"{ts.sell_strike/underlying_price:.2f}"),
        }
        ts.entry_allowed = all(c for c, _ in ts.conditions.values())
        ts.description = (
            f"FULL+HIGH → 卖OTM Put spread. "
            f"卖K={ts.sell_strike}, 买K={ts.buy_strike}, "
            f"宽{ts.spread_width_pct}%, DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # QUADRANT: FULL + IV MID → SELL_PUT_SPREAD (wider OTM)
    # ============================================================
    elif direction == "FULL" and iv_level == "MID":
        ts.action = "SELL_PUT_SPREAD"
        otm_dist = atr_pct * 1.0
        ts.sell_strike = round(underlying_price * (1 - otm_dist), 2)
        ts.buy_strike = round(ts.sell_strike * 0.95, 2)
        ts.spread_width_pct = round((ts.sell_strike - ts.buy_strike) / ts.sell_strike * 100, 1)

        cond1 = weeks_since_flip <= 2
        cond2 = True  # MID 级别通过 IV 要求
        cond3 = ts.sell_strike / underlying_price <= 0.92

        ts.conditions = {
            "WTS翻多≤2周": (cond1, f"当前{weeks_since_flip}周"),
            "IV≥50th分位": (True, "MID区间→通过"),
            "Put strike安全距离(≤0.92)": (cond3, f"{ts.sell_strike/underlying_price:.2f}"),
        }
        ts.entry_allowed = all(c for c, _ in ts.conditions.values())
        ts.description = (
            f"FULL+MID → 卖OTM Put spread(宽). "
            f"卖K={ts.sell_strike}, 买K={ts.buy_strike}, "
            f"宽{ts.spread_width_pct}%, DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # QUADRANT: FULL + IV LOW → BUY_CALL
    # ============================================================
    elif direction == "FULL" and iv_level == "LOW":
        ts.action = "BUY_CALL"
        cond1 = weeks_since_flip >= 1
        ts.conditions = {"WTS持续多头≥1周": (cond1, f"当前{weeks_since_flip}周")}
        ts.entry_allowed = cond1
        ts.description = (
            f"FULL+LOW → 买ATM Call. "
            f"方向确定+权利金便宜→直接买方向. DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # QUADRANT: FLAT + IV HIGH/MID → SELL_CALL_SPREAD
    # ============================================================
    elif direction == "FLAT" and iv_level in ("HIGH", "MID"):
        ts.action = "SELL_CALL_SPREAD"
        otm_dist = atr_pct * (0.8 if iv_level == "HIGH" else 1.0)
        ts.sell_strike = round(underlying_price * (1 + otm_dist), 2)
        ts.buy_strike = round(ts.sell_strike * 1.05, 2)
        ts.spread_width_pct = round((ts.buy_strike - ts.sell_strike) / ts.sell_strike * 100, 1)

        cond1 = weeks_since_flip <= 3  # WTS 翻空 3 周以内
        ts.conditions = {"WTS翻空≤3周": (cond1, f"当前{weeks_since_flip}周(翻多)")}
        ts.entry_allowed = cond1
        ts.description = (
            f"FLAT+{iv_level} → 卖OTM Call spread. "
            f"卖K={ts.sell_strike}, 买K={ts.buy_strike}, "
            f"宽{ts.spread_width_pct}%, DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # QUADRANT: FLAT + IV LOW → WAIT
    # ============================================================
    elif direction == "FLAT" and iv_level == "LOW":
        ts.action = "WAIT"
        ts.entry_allowed = False
        ts.description = "FLAT+LOW → 空仓。没有方向+没有溢价=不值得动手。"

    # 黑名单检查
    if direction == "FULL" and weeks_since_flip > 5:
        ts.hold_advice = (
            "⚠️ WTS已连涨超5周，警惕趋势延伸风险。"
            "已持仓建议收紧止损，未持仓不追入。"
        )
    elif direction == "FULL" and weeks_since_flip > 3:
        ts.hold_advice = "WTS连涨中，注意IV压缩和回调风险。"

    # 持仓建议
    if direction == "FULL":
        ts.hold_advice += " | 已持仓: 继续持有，止损=本周最低价。离场=WTS翻空。"
    else:
        ts.hold_advice += " | 已持仓: 立即平仓。"

    return ts


def compute_exit_rules(signal_result: dict,
                       entry_price: float,
                       current_price: float,
                       days_held: int,
                       option_type: str) -> dict:
    """
    持仓退出规则。

    Returns:
        {
            "should_exit": bool,
            "reason": str,
            "stop_price": float or None,
        }
    """
    # 信号翻转 → 无条件退出
    if signal_result["target"] == 0:
        return {"should_exit": True, "reason": "WTS翻空", "stop_price": None}

    # Spread 止盈
    if option_type in ("SELL_PUT_SPREAD", "SELL_CALL_SPREAD"):
        # 简化: 获利>60% → 止盈
        # 实盘用 spread 当前价值 / 开仓价值 < 0.4 判断
        pass

    return {"should_exit": False, "reason": "", "stop_price": None}
