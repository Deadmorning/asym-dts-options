# asym-dts-options

H/D3D4 策略的期权表达层 — 用 IV 做表达优化，方向信号不动。

## 一句话

`WTS/DTS` 决定方向，`IV` 决定表达方式。方向决策和表达决策分层，互不污染。

---

## 设计原则

**方向决定期权侧（FULL→Call侧，FLAT→Put侧），IV决定买/卖方（HIGH→卖方收溢价，否则→买方跟方向）。**

H 策略在 ETF 上只有一种表达：买或不买。期权市场多给了一个维度：权利金定价。用这个维度优化表达，不改造方向信号。

### 决策矩阵

```
              IV HIGH                 IV MID                  IV LOW
              ────────                ──────                  ──────
FULL    卖OTM Put spread        买ATM Call              买虚值Call
        (收恐慌溢价)              (正常趋势跟随)            (便宜买方向)

FLAT    卖OTM Call spread       买ATM Put               买虚值Put
        (收恐慌溢价)              (正常趋势跟随做空)         (便宜做空)
```

| 象限 | 核心逻辑 |
|------|---------|
| FULL/HIGH | 方向刚确认+恐慌溢价还在→卖 Put 收双份 |
| FULL/MID | 方向对+IV正常→付公平权利金跟方向 |
| FULL/LOW | 方向对+权利金便宜→买虚值，性价比最高 |
| FLAT/HIGH | 下跌确认+恐慌溢价→卖 Call 收双份 |
| FLAT/MID | 下跌确认+IV正常→付公平权利金做空 |
| FLAT/LOW | 慢熊+期权便宜→买虚值 Put 最优场景 |

核心约束：**H 状态机不改一行。** 只加表达层。

---

## 项目结构

```
asym-dts-options/
├── strategy/
│   ├── signals.py          # H 策略信号 (WTS/DTS/状态机)
│   ├── iv_engine.py        # IV 获取 + 分位计算 + 冷启动
│   ├── decision_matrix.py  # 四象限决策 + 入场/退出/滚仓/持仓管理
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

输出示例：

```
[1/5] 加载数据...  标的: 510500 @ 8.769  日期: 2026-05-08
[2/5] 计算 H 策略信号...  方向: FULL  分支: 连续UP → long  WTS翻多周数: 5
[3/5] 获取 IV 数据...  IV=23.0%  分位=50th  档=MID  DTE=47d
[4/5] 计算 ATR...  ATR% = 1.52%
[5/5] 决策矩阵...
============================================================
  交易信号: BUY_CALL
  入场允许: ✅
  持仓状态: EXTENDED
  止损价: 8.68
  FULL+MID → 买ATM Call(正常趋势跟随). 入场允许=True.
  ⚠️ WTS连涨5周，趋势延伸风险高。不开新仓。已持仓→止损收紧至 8.68。
============================================================
```

### 回测验证

```bash
python analysis.py --start 2024-01-02 --export
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
| 冷启动 | 前 20 个交易日强制 WAIT（IV 数据不足以计算分位） |
| 决策矩阵 | 六象限 → 选期权结构 |

### 入场规则

```
FULL + IV HIGH (卖 Put spread):
  □ WTS 刚翻多 ≤ 2 周
  □ IV ≥ 50th 分位
  □ 卖 Put strike ≤ 当前价的 92%
  → 三个全部 PASS → 开仓

FULL + IV MID/LOW (买 Call):
  □ WTS 持续多 ≥ 1 周
  → 开仓。MID 买 ATM，LOW 可买虚值

FLAT + IV HIGH (卖 Call spread):
  □ WTS 翻空 ≤ 3 周
  → 开仓

FLAT + IV MID/LOW (买 Put):
  □ WTS 翻空 ≤ 3 周
  → 开仓。MID 买 ATM，LOW 可买虚值
```

### 退出规则

| 触发条件 | 操作 |
|----------|------|
| WTS 信号翻转 | 无条件平仓 |
| 卖方 spread: 标的价格触及卖端 strike | 止损平仓 |
| Long Call/Put: 剩余 DTE ≤ 7 天 | 滚仓（平旧开新） |
| Spread 价值衰减到开仓价 40% 以下 | 止盈平仓（实盘监控） |

### 持仓状态管理（与入场门控分离）

```
周数    FULL侧                      FLAT侧
───────────────────────────────────────────────────
0       NOPOSITION（等下周确认）     —
≤1~2    ENTRY_WINDOW（可开新仓）     FRESH_FLIP（可开新仓）
≤5      MID_TREND（不开新仓，止损收紧） MID_TREND（不开新仓，止损收紧）
>5      EXTENDED（不开新仓，收紧止损，考虑减仓） EXTENDED（同上）
```

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

## 与 H/D3D4 的关系

```
asym-dts-h (ETF)     →  510500 原版，不能做空，二元全仓进出
asym-dts-h-d3d4      →  节假日 overlay，非日常策略
asym-dts-options     →  同一个 H 信号 × 期权表达层
```

三个项目并行不替代。

---

## 失败条件

| 类型 | 条件 | 响应 |
|------|------|------|
| Cyclical | IV 长期低位，无溢价可收 | 策略退化至一年几次买 Call/Put |
| Mechanism decay | IV 飙升幅度缩小 | 监控 70th 分位 IV / 中位数 IV 比值 |
| Structural | 期权做市规则改变 | 重新验证策略前提 |

---

## 修正记录

| # | 问题 | 修正前 | 修正后 |
|----|------|--------|--------|
| 1 | IV MID 场景卖方逻辑 | FULL+MID→SELL_PUT_SPREAD | FULL+MID→BUY_CALL（MID无溢价可收割） |
| 2 | FLAT放弃确定性方向 | FLAT+LOW→WAIT | FLAT+LOW→BUY_PUT（慢熊+便宜Put最优） |
| 3 | weeks_since_flip死区 | 入场被拒后系统沉默 | 四段持仓状态管理，止损有具体价位 |
| 4 | Long没有滚仓 | 无 | DTE≤7天触发滚仓 |
| 5 | 卖方没有止损 | 仅WTS翻空/60%止盈 | 触及卖端strike→立即平仓 |
| 6 | IV冷启动 | 默认MID | 前20天强制WAIT |

## 已完成的验证

| 日期 | 信号 | IV | 决策 | 入场 | 持仓状态 |
|------|------|----|----|------|---------|
| 2026-05-08 | FULL (WTS=1,连续UP,第5周) | 23.0% (MID) | BUY_CALL | ✅ | EXTENDED |

验证结论：FULL+MID→BUY_CALL（正常趋势跟随）。WTS翻多已5周，EXTENDED状态 → 不开新仓，已持仓止损8.68。

---

## 免责声明

本仓库仅为策略研究与回测资料归档，**不构成任何投资建议**。期权交易存在额外风险（Gamma 风险、IV 风险、跳空风险），回测收益不代表未来收益。
