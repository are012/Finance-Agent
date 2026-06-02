# PROJECT_SPEC.md

# Chart-Only Korean Market Systematic Trading Research Framework

## 0. Mission

Build a reproducible Python research framework for Korean stock-market systematic trading using ONLY chart-derived data.

The framework must allow an agent to:

1. Generate one explicit trading hypothesis at a time.
2. Convert that hypothesis into a fully specified strategy.
3. Backtest the strategy conservatively.
4. Validate the strategy out-of-sample.
5. Critique the strategy for leakage, overfitting, unrealistic execution, fragility, and data-quality problems.
6. Log every experiment, including failed ones.
7. Continue research until the configured research budget is exhausted or a candidate satisfies all validation gates.
8. Select the best validated candidate using pre-defined scoring rules.
9. Evaluate the final holdout only once.
10. Produce a final report with either:
   - PASS: strategy is a research candidate for paper trading,
   - FAIL: no robust strategy found,
   - NEEDS_MORE_RESEARCH: evidence is inconclusive.

This project is for research only. Do not implement live trading, broker integration, order placement, account login, or real-money execution.

---

## 1. Hard Constraints

### 1.1 Allowed Data

Only the following data may be used:

- date
- symbol
- open
- high
- low
- close
- adjusted_close
- volume
- traded_value
- market
- listing_status, if available
- chart-derived indicators computed from the above fields

Allowed chart-derived features include, but are not limited to:

- simple returns
- log returns
- gap returns
- intraday range
- candle body size
- upper/lower wick size
- moving averages
- moving-average distance
- moving-average crossover
- momentum
- short-term reversal
- long-term reversal
- rolling volatility
- ATR
- Bollinger Bands
- RSI
- MACD
- high/low breakout
- Donchian-style channels
- volume moving averages
- volume surge
- traded-value filters
- turnover-like proxies when data permits
- VWAP-like approximations when available from OHLCV only

### 1.2 Forbidden Data

Do not use:

- fundamentals
- financial statements
- earnings data
- analyst reports
- news
- disclosures
- social media
- macroeconomic indicators
- investor-flow data
- foreign/institutional/retail net buying data
- order book data unless explicitly available as chart data in the local dataset
- future returns in signal generation
- future highs/lows in signal generation
- current index membership applied backward in time
- any feature that cannot be known at the decision timestamp
- any internet data source during test runs

### 1.3 Anti-Goal

The goal is NOT to maximize backtest return at any cost.

The goal is to build a conservative research system that prefers:

- no lookahead bias,
- no final-holdout contamination,
- realistic execution assumptions,
- repeatable results,
- full experiment logging,
- robustness checks,
- risk-adjusted performance,
- transparent failure reporting.

A strategy with lower return but stronger robustness is preferred over a fragile high-return strategy.

---

## 2. Expected Project Structure

Create or adapt the repository into a clean Python project.

Recommended structure:

```text
.
├── README.md
├── PROJECT_SPEC.md
├── pyproject.toml
├── configs
│   └── example.yaml
├── data
│   ├── sample
│   │   └── synthetic_ohlcv.csv
│   └── README.md
├── app
│   ├── __init__.py
│   ├── run_research.py
│   ├── final_report.py
│   └── run_one_hypothesis.py
├── research
│   ├── __init__.py
│   ├── data_loader.py
│   ├── schema.py
│   ├── features.py
│   ├── hypothesis.py
│   ├── strategy.py
│   ├── backtester.py
│   ├── costs.py
│   ├── metrics.py
│   ├── validation.py
│   ├── critic.py
│   ├── scoring.py
│   ├── ledger.py
│   ├── reporting.py
│   └── utils.py
├── tests
│   ├── test_schema.py
│   ├── test_features_no_lookahead.py
│   ├── test_backtester_next_bar_execution.py
│   ├── test_costs.py
│   ├── test_metrics.py
│   ├── test_validation_split.py
│   ├── test_hypothesis_schema.py
│   └── test_ledger.py
└── outputs
    ├── ledger
    ├── reports
    └── artifacts