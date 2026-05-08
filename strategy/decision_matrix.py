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
    # QUADRANT: FULL + IV MID → BUY_CALL（正常趋势跟随）
    # ============================================================
    # MID IV 没有恐慌溢价可收割，不应卖 Put。
    # 正常市场下方向对的唯一合理表达是买方结构。
    elif direction == "FULL" and iv_level == "MID":
        ts.action = "BUY_CALL"
        ts.entry_allowed = (weeks_since_flip >= 1)
        ts.conditions = {
            "WTS持续多头≥1周": (ts.entry_allowed, f"当前{weeks_since_flip}周"),
        }
        ts.description = (
            f"FULL+MID → 买ATM Call(正常趋势跟随). "
            f"方向确定,IV合理→付公平权利金买方向. DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # QUADRANT: FULL + IV LOW → BUY_CALL（便宜买方向）
    # ============================================================
    elif direction == "FULL" and iv_level == "LOW":
        ts.action = "BUY_CALL"
        ts.entry_allowed = (weeks_since_flip >= 1)
        ts.conditions = {"WTS持续多头≥1周": (ts.entry_allowed, f"当前{weeks_since_flip}周")}
        ts.description = (
            f"FULL+LOW → 买虚值Call(便宜买方向). "
            f"方向确定+权利金便宜→可买稍虚值. DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # QUADRANT: FLAT + IV HIGH → SELL_CALL_SPREAD
    # ============================================================
    elif direction == "FLAT" and iv_level == "HIGH":
        ts.action = "SELL_CALL_SPREAD"
        otm_dist = atr_pct * 0.8
        ts.sell_strike = round(underlying_price * (1 + otm_dist), 2)
        ts.buy_strike = round(ts.sell_strike * 1.05, 2)
        ts.spread_width_pct = round((ts.buy_strike - ts.sell_strike) / ts.sell_strike * 100, 1)

        cond1 = weeks_since_flip <= 3
        ts.conditions = {"WTS翻空≤3周": (cond1, f"当前{weeks_since_flip}周")}
        ts.entry_allowed = cond1
        ts.description = (
            f"FLAT+HIGH → 卖OTM Call spread. "
            f"卖K={ts.sell_strike}, 买K={ts.buy_strike}, "
            f"宽{ts.spread_width_pct}%, DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # QUADRANT: FLAT + IV MID → BUY_PUT（正常趋势跟随做空）
    # ============================================================
    # FLAT = WTS=0 = 下跌方向确定。默认跟着方向走——买Put。
    # 卖Call spread只应在IV HIGH时触发。
    elif direction == "FLAT" and iv_level == "MID":
        ts.action = "BUY_PUT"
        ts.entry_allowed = (weeks_since_flip <= 3)
        ts.conditions = {
            "WTS翻空确认": (ts.entry_allowed, f"翻空{weeks_since_flip}周"),
        }
        ts.description = (
            f"FLAT+MID → 买ATM Put(正常趋势跟随做空). "
            f"方向确定,IV合理→付公平权利金做空. DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # QUADRANT: FLAT + IV LOW → BUY_PUT（便宜买Put做空）
    # ============================================================
    elif direction == "FLAT" and iv_level == "LOW":
        ts.action = "BUY_PUT"
        ts.entry_allowed = (weeks_since_flip <= 3)
        ts.conditions = {
            "WTS翻空确认": (ts.entry_allowed, f"翻空{weeks_since_flip}周"),
        }
        ts.description = (
            f"FLAT+LOW → 买虚值Put(便宜做空). "
            f"慢熊+期权便宜=最优Put买入场景. DTE≈{dte}d. "
            f"入场允许={ts.entry_allowed}"
        )

    # ============================================================
    # 持仓状态管理（与入场门控分离）
    # ============================================================
    # 入场门控判断是否开新仓
    # 持仓管理判断已有仓位如何维护

    if direction == "FULL":
        if weeks_since_flip == 0:
            ts.position_state = "NO_POSITION"
            ts.stop_loss = None
            ts.position_advice = "无持仓。WTS刚翻多，等下周确认后入场。"
        elif weeks_since_flip <= 2:
            ts.position_state = "ENTRY_WINDOW"
            ts.stop_loss = None
            ts.position_advice = (
                "入场窗口期。若已持仓→正常止损(本周最低价×0.98)。"
                f"若未持仓→{'可开新仓' if ts.entry_allowed else '入场条件待满足'}。"
            )
        elif weeks_since_flip <= 5:
            ts.position_state = "MID_TREND"
            ts.stop_loss = round(underlying_price * (1 - atr_pct * 1.5), 2)
            ts.position_advice = (
                f"趋势中段。不开新仓。已持仓→止损收紧至 {ts.stop_loss}。"
                "WTS翻空→立即平仓。"
            )
        else:
            ts.position_state = "EXTENDED"
            ts.stop_loss = round(underlying_price * (1 - atr_pct * 1.0), 2)
            ts.position_advice = (
                f"⚠️ WTS连涨{weeks_since_flip}周，趋势延伸风险高。"
                f"不开新仓。已持仓→止损收紧至 {ts.stop_loss}（最近周最低价）。"
                "考虑减仓1/2。WTS翻空→立即平仓。"
            )
    else:
        if weeks_since_flip <= 1:
            ts.position_state = "FRESH_FLIP"
            ts.stop_loss = round(underlying_price * (1 + atr_pct * 1.5), 2)
            ts.position_advice = (
                f"WTS刚翻空。若已做空→止损={ts.stop_loss}。"
                f"{'可开新仓' if ts.entry_allowed else '入场条件待满足'}。"
            )
        elif weeks_since_flip <= 5:
            ts.position_state = "MID_TREND"
            ts.stop_loss = round(underlying_price * (1 + atr_pct * 1.0), 2)
            ts.position_advice = (
                f"下跌趋势中。不开新仓。已持仓→止损={ts.stop_loss}。"
                "WTS翻多→立即平仓。"
            )
        else:
            ts.position_state = "EXTENDED"
            ts.stop_loss = round(underlying_price * (1 + atr_pct * 0.8), 2)
            ts.position_advice = (
                f"⚠️ WTS连跌{weeks_since_flip}周，趋势延伸但反转风险累积。"
                f"已持仓→止损收紧至 {ts.stop_loss}。"
                "考虑减仓。WTS翻多→立即平仓。"
            )

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
