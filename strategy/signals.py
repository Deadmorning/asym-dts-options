"""
H 策略信号模块 — WTS/DTS 计算
===============================
与 asym-dts-h Ptrade 版 1:1 一致，参数全部冻结。
"""

import pandas as pd
import numpy as np
from datetime import timedelta

# ============================================================
# 参数（冻结，严禁调参）
# ============================================================
W_FLAT, W_SAME, W_REV = 0.018, 0.009, 0.012
D_FLAT, D_SAME, D_REV = 0.007, 0.003, 0.003


# ============================================================
# 核心函数
# ============================================================
def amp(o: float, h: float, l: float) -> float:
    return (h - l) / o if o else 0.0


def classify(o: float, c: float, a: float, flat: float) -> str:
    if a < flat:
        return "FLAT"
    return "UP" if c >= o else "DOWN"


def seven_rules(pc: str, cc: str, pa: float, ca: float,
                same: float, rev: float) -> int | None:
    """7 条规则，返回 1 / 0 / -1 / None"""
    if pc == "FLAT" and cc == "FLAT":
        return None
    if (pc in ("FLAT", "UP") and cc == "UP") or (pc == "UP" and cc == "FLAT"):
        return 1
    if (pc in ("FLAT", "DOWN") and cc == "DOWN") or (pc == "DOWN" and cc == "FLAT"):
        return 0
    d = abs(ca - pa)
    if pc == "UP" and cc == "UP":
        return 1 if d >= same else None
    if pc == "DOWN" and cc == "DOWN":
        return -1 if d >= same else None
    if pc == "UP" and cc == "DOWN":
        return -1 if d >= rev else None
    if pc == "DOWN" and cc == "UP":
        return 1 if d >= rev else None
    return None


def compute_wts(df: pd.DataFrame,
                flat: float = W_FLAT,
                same: float = W_SAME,
                rev: float = W_REV) -> dict:
    """
    H 版 WTS：仅对完整 5 日周计算（周一用上周数据重算）。

    Args:
        df: DataFrame with columns [date, open, high, low, close]

    Returns:
        {week_num_str: (signal, prev_class, curr_class)}
          signal ∈ {0, 1}
          prev_class, curr_class ∈ {"UP", "DOWN", "FLAT"}
    """
    d = df.copy()
    d["week"] = d["date"].dt.to_period("W-MON")
    d["week_num"] = d["date"].dt.strftime("%Y-%W")
    weekly = d.groupby("week").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "date": "first", "week_num": "first",
    }).reset_index()
    wc = d.groupby("week").size()
    weekly["day_count"] = weekly["week"].map(wc)
    weekly = weekly[weekly["day_count"] >= 5].copy().reset_index(drop=True)

    if len(weekly) < 2:
        return {}

    signals = {}
    prev_sig = 1
    for i in range(1, len(weekly)):
        pr = weekly.iloc[i - 1]
        cr = weekly.iloc[i]
        pa = amp(pr["open"], pr["high"], pr["low"])
        ca = amp(cr["open"], cr["high"], cr["low"])
        pc = classify(pr["open"], pr["close"], pa, flat)
        cc = classify(cr["open"], cr["close"], ca, flat)
        ns = seven_rules(pc, cc, pa, ca, same, rev)
        if ns is not None:
            prev_sig = ns
        signals[cr["week_num"]] = (1 if prev_sig == 1 else 0, pc, cc)
    return signals


def compute_dts(prev_bar: pd.Series, curr_bar: pd.Series) -> int | None:
    """
    用两根日线 K 算 DTS。
    Returns: 1 (up), 0 (down/neutral), or None
    """
    pa = amp(prev_bar["open"], prev_bar["high"], prev_bar["low"])
    ca = amp(curr_bar["open"], curr_bar["high"], curr_bar["low"])
    pc = classify(prev_bar["open"], prev_bar["close"], pa, D_FLAT)
    cc = classify(curr_bar["open"], curr_bar["close"], ca, D_FLAT)
    ns = seven_rules(pc, cc, pa, ca, D_SAME, D_REV)
    if ns == 1:
        return 1
    if ns in (0, -1):
        return 0
    return None


def h_state_machine(wts_signal: int, last_wts: int,
                    prev_class: str, curr_class: str,
                    dts_decision: int) -> int:
    """
    H 状态机 5 分支 → target ∈ {0, 1}.

    1. WTS=0 → 空
    2. last_wts=0 & WTS=1 → 多 (new_bull)
    3. prev=UP & curr=UP → 多
    4. prev=DOWN & curr=DOWN → 空
    5. else → DTS 决定
    """
    if wts_signal == 0:
        return 0
    if last_wts == 0 and wts_signal == 1:
        return 1
    if prev_class == "UP" and curr_class == "UP":
        return 1
    if prev_class == "DOWN" and curr_class == "DOWN":
        return 0
    return 1 if dts_decision == 1 else 0


def run_signal_pipeline(df: pd.DataFrame,
                        today: pd.Timestamp) -> dict:
    """
    完成一个交易日的 H 策略信号计算。

    Args:
        df: 历史日线 [date, open, high, low, close]，按日期升序，含今日
        today: 当前日期

    Returns:
        {
            "target": 0 or 1,
            "wts_signal": int,
            "prev_class": str,
            "curr_class": str,
            "last_wts": int,
            "dts_decision": int,
            "dts_today": int|None,
            "branch": str,
            "current_week_num": str,
            "weeks_since_flip": int,
        }
    """
    current_week_num = today.strftime("%Y-%W")

    # WTS：用上周五之前的数据
    days_since_friday = (today.weekday() + 2) % 7
    if days_since_friday == 0:
        days_since_friday = 7
    last_friday = today - timedelta(days=days_since_friday)
    last_week_data = df[df["date"] <= last_friday].copy()

    wts_signals = compute_wts(last_week_data)
    if not wts_signals:
        return {"target": 1, "error": "no_wts_data"}

    if current_week_num in wts_signals:
        wts_state = wts_signals[current_week_num]
    else:
        wts_state = list(wts_signals.values())[-1]

    wts_signal, prev_class, curr_class = wts_state

    # last_wts
    all_weeks = sorted(wts_signals.keys())
    try:
        idx = all_weeks.index(current_week_num)
    except ValueError:
        idx = len(all_weeks) - 1
    prev_week_num = all_weeks[idx - 1] if idx > 0 else all_weeks[0]
    last_wts = wts_signals.get(prev_week_num, (1, "FLAT", "FLAT"))[0]

    # DTS
    if len(df) >= 3:
        dts_yesterday = compute_dts(df.iloc[-3], df.iloc[-2])
        dts_today = compute_dts(df.iloc[-2], df.iloc[-1])
    else:
        dts_yesterday = 1
        dts_today = None
    dts_decision = dts_yesterday if dts_yesterday is not None else 1

    # 状态机
    if wts_signal == 0:
        branch = "WTS=0 → flat"
    elif last_wts == 0 and wts_signal == 1:
        branch = "new_bull → long"
    elif prev_class == "UP" and curr_class == "UP":
        branch = "连续UP → long"
    elif prev_class == "DOWN" and curr_class == "DOWN":
        branch = "连续DOWN → flat"
    else:
        branch = f"模糊区间 → DTS({dts_decision})"

    target = h_state_machine(wts_signal, last_wts, prev_class, curr_class, dts_decision)

    # 计算翻多周数
    weeks_since_flip = 0
    for wk in reversed(all_weeks):
        s, _, _ = wts_signals[wk]
        if s == 1:
            weeks_since_flip += 1
        else:
            break

    return {
        "target": target,
        "wts_signal": wts_signal,
        "prev_class": prev_class,
        "curr_class": curr_class,
        "last_wts": last_wts,
        "dts_decision": dts_decision,
        "dts_today": dts_today,
        "branch": branch,
        "current_week_num": current_week_num,
        "weeks_since_flip": weeks_since_flip,
        "wts_history": {k: v for k, v in list(wts_signals.items())[-12:]},
    }
