#!/usr/bin/env python3
"""
asym-dts-options — 日频策略执行入口
=====================================

用法:
    python daily.py                       # 默认 510500
    python daily.py --etf 510050          # 上证50
    python daily.py --etf 510500 --json   # JSON 输出

依赖:
    pip install -r requirements.txt
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy.framework import run_daily

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default="sh000905")
    parser.add_argument("--etf", default="510500")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_daily(
        symbol_index=args.index,
        symbol_etf=args.etf,
        verbose=not args.json,
    )

    if args.json:
        import json
        if "signal" in result and "wts_history" in result["signal"]:
            del result["signal"]["wts_history"]
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
