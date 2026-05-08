# asym-dts-options

H/D3D4 策略的期权表达层 — 用 IV 做表达优化，方向信号不动。

## 一句话

`WTS/DTS` 决定方向（要不要暴露），`IV` 决定表达方式（用什么工具暴露）。方向决策和表达决策分层，互不污染。

---

## 设计哲学

H 策略在 ETF 上只有一种表达：买或不买。期权市场多给了一个维度：权利金定价。用这个维度优化表达，不改造方向信号。

```
              IV HIGH                 IV MID                  IV LOW
              ────────                ──────                  ──────
FULL    卖OTM Put spread        买ATM Call              买虚值Call
        (收恐慌溢价)              (正常趋势跟随)            (便宜买方向)

FLAT    卖OTM Call spread       买ATM Put               买虚值Put
        (收恐慌溢价)              (正常趋势跟随做空)         (便宜做空)
```

核心约束：**H 状态机不改一行。** 只加表达层。

**原则：方向决定买/卖侧（FULL→Call侧，FLAT→Put侧），IV 决定是买方还是卖方（HIGH→卖方收溢价，否则→买方跟方向）。**

---

## 项目结构

```
asym-dts-options/
├── strategy/
│   ├── signals.py          # H 策略信号 (WTS/DTS/状态机)
│   ├── iv_engine.py        # IV 获取 + 分位计算
│   ├── decision_matrix.py  # 四象限决策 + 入场/退出规则
│   └── framework.py        # 日频执行器主框架
├── data/
│   └── fetch.py            # 数据获取 (AKShare)
├── backtests/
│   └── validate.py         # H 策略 ETF 回测验证
├── analysis.py             # 交互式信号分析
├── daily.py                # 每日运行入口
├── requirements.txt
└── README.md
```

---

## 快速开始

```bash
pip install -r requirements.txt
```

### 每日运行（收盘后）

```bash
python daily.py                    # 默认 510500
python daily.py --etf 510050      # 上证50
python daily.py --json            # JSON 输出
```

输出：

```
[1/5] 加载数据...
      标的: 510500 @ 8.769
      日期: 2026-05-08
[2/5] 计算 H 策略信号...
      方向: FULL
      分支: 连续UP → long
      WTS翻多周数: 5
[3/5] 获取 IV 数据...
      IV=23.0%  分位=50th  档=MID  DTE=47d
[4/5] 计算 ATR...
      ATR% = 1.52%
[5/5] 决策矩阵...

============================================================
  交易信号: SELL_PUT_SPREAD
  入场允许: ❌
  FULL+MID → 卖OTM Put spread(宽). 卖K=8.61, 买K=8.18, 宽5.0%, DTE≈47d.
  入场允许=False. WTS翻多已5周,错过最佳卖Put窗口.
  ⚠️ WTS已连涨超5周，警惕趋势延伸风险.
============================================================
```

### 回测验证

```bash
python analysis.py --start 2024-01-02 --export
```

输出 H 策略在 ETF 上的信号表现，验证方向信号质量：

```
  H 策略 ETF 回测 汇总
            period: 2024-01-02 ~ 2026-05-08
    bh_return_pct: 72.20
strategy_return_pct: 49.20
  excess_return_pct: -23.00
        num_trades: 36
      win_rate_pct: 55.6
     full_pct_of_time: 51.2
```

---

## 策略框架

### 信号层（不改，继承自 asym-dts-h）

| 组件 | 描述 |
|------|------|
| WTS | 周线趋势信号，仅对完整 5 日周计算，每周一重算 |
| DTS | 日线趋势信号，用昨日+今日两根K线 |
| 状态机 | 5 分支 → 输出 FULL (1) 或 FLAT (0) |
| 参数 | 全部冻结: W_FLAT/SAME/REV=0.018/0.009/0.012, D_FLAT/SAME/REV=0.007/0.003/0.003 |

### IV 表达层（新增）

| 组件 | 描述 |
|------|------|
| IV 获取 | 东方财富 API → AKShare `option_value_analysis_em` → 直接拿IV |
| 分位计算 | 滚动 252 日 → IV ≥ 70th = HIGH, ≤ 30th = LOW, 其余 MID |
| 决策矩阵 | 四象限 → 选期权结构 |

### 入场规则

```
FULL + IV HIGH (卖 Put spread):
  □ WTS 刚翻多 ≤ 2 周
  □ IV ≥ 50th 分位
  □ 卖 Put strike ≥ 当前价的 0.92 以下
  → 三个全部 PASS → 开仓

FULL + IV MID/LOW (买 Call):
  □ WTS 持续多 ≥ 1 周
  → 开仓。MID 买 ATM，LOW 可买虚值。

FLAT + IV HIGH (卖 Call spread):
  □ WTS 翻空 ≤ 3 周
  → 开仓。

FLAT + IV MID/LOW (买 Put):
  □ WTS 翻空 ≤ 3 周
  → 开仓。MID 买 ATM，LOW 可买虚值。
```

### 退出规则

| 触发条件 | 操作 |
|----------|------|
| Spread 价值衰减到开仓价 40% 以下 | 止盈平仓 |
| 标的价格触及卖端 strike | 止损平仓 |
| WTS 信号翻转 | 无条件平仓（继承 H 铁律） |
| 到期 | 持有到期结算 |

### 不开仓黑名单

- IV 在 30th-70th 分位 + 方向 FLAT
- 信号翻转后 3 天以内
- 距到期日 < 7 天
- WTS=1 连涨超 5 周且没回调

---

## 标的映射

| 标的 | 期权代码 | WTS参数 | 优先级 | 说明 |
|------|---------|---------|--------|------|
| 中证500 | 510500 | 5日WTS | **1** | 信号原生环境，行为 Alpha 最纯 |
| 上证50 | 510050 | 20日WTS | 2 | 期权流动性最优，需换参数匹配政策周期 |
| 创业板 | 159915 | 5日WTS | 3 | 信号质量最高但 IV 偏贵，需 Bull Call Spread |
| 沪深300 | 510300 | 5日WTS | 4 | 中位，无结构性优势 |
| 科创50 | 588000 | — | 排除 | 事件驱动 ≠ 趋势跟踪，信号机制不兼容 |

---

## 依赖

```
akshare >= 1.15.0
pandas  >= 2.0.0
numpy   >= 1.24.0
scipy   >= 1.10.0
requests
```

东方财富 API (`push2.eastmoney.com`) — 免费，无需 API Key。

---

## 与 H/D3D4 的关系

```
asym-dts-h (ETF)     →  510500 原版，不能做空，二元全仓进出
asym-dts-h-d3d4      →  节假日 overlay，非日常策略
asym-dts-options     →  同一个 H 信号 × 期权表达层
```

三个项目并行不替代。期权版赚的是"方向趋势的钱 + 期权定价偏差的钱"。

---

## 失败条件

| 类型 | 条件 | 响应 |
|------|------|------|
| Cyclical | IV 长期低位，无溢价可收 | 策略退化至一年几次买 Call |
| Mechanism decay | IV 飙升幅度缩小 | 监控 70th 分位 IV / 中位数 IV 比值 |
| Structural | 期权做市规则改变 | 重新验证策略前提 |

---

## 已完成的验证

| 日期 | 信号 | IV | 决策 | 入场 |
|------|------|----|----|------|
| 2026-05-08 | FULL (WTS=1,连续UP,第5周) | 23.0% (MID) | SELL_PUT_SPREAD | ❌ WTS翻多超2周 |

验证结论：WTS 从 W12(4月中旬) 翻多至今已 5 周，错过最佳卖 Put 窗口。IV 已从恐慌高位均值回归至 ~23%。当前不追入，等下一信号。

---

## 免责声明

本仓库仅为策略研究与回测资料归档，**不构成任何投资建议**。期权交易存在额外风险（Gamma 风险、IV 风险、跳空风险），回测收益不代表未来收益。
