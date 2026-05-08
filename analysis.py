"""
信号分析 — 交互式分析
======================

用法: python analysis.py [--start 2024-01-01] [--export]
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtests.validate import backtest_h_etf, summarize_backtest


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default="sh000905")
    parser.add_argument("--etf", default="510500")
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default=None)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    print(f"回测: {args.start} ~ {args.end or '至今'}")
    print(f"指数: {args.index}  ETF: {args.etf}")
    print()

    df = backtest_h_etf(
        symbol_index=args.index,
        symbol_etf=args.etf,
        start=args.start,
        end=args.end,
    )

    if df.empty:
        print("无数据")
        return

    summary = summarize_backtest(df)

    print("=" * 60)
    print("  H 策略 ETF 回测 汇总")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k:>20s}: {v}")

    # WTS 信号分布
    print()
    print(f"  WTS=1 占比: {df['target'].mean()*100:.1f}%")
    print(f"  总交易天数: {len(df)}")

    if args.export:
        out = f"backtest_{args.etf}_{args.start}.csv"
        df.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"\n导出: {out}")


if __name__ == "__main__":
    main()
