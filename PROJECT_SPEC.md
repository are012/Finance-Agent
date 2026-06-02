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
```

The exact structure may be adjusted if the existing repository already has a structure, but all required responsibilities must exist somewhere clear and testable.

---

## 3. Technology Requirements

Use Python.

Prefer simple, reliable dependencies:

* pandas
* numpy
* pydantic or dataclasses
* PyYAML
* pytest
* matplotlib, only for report charts if needed
* sqlite3 from the standard library, or JSONL if simpler

The framework must run without internet access.

The framework must run end-to-end on sample or synthetic OHLCV data included in the repository.

Do not require proprietary data to run tests.

---

## 4. Data Schema

Support local CSV and Parquet files.

The canonical OHLCV schema is:

```text
date: datetime-like
symbol: string
open: float
high: float
low: float
close: float
adjusted_close: float
volume: float
traded_value: float
market: string
listing_status: string, optional
```

Required behavior:

1. Validate required columns.
2. Sort data by symbol and date.
3. Deduplicate duplicated symbol/date rows deterministically.
4. Reject or flag rows with impossible OHLC relationships:

   * high < low
   * high < open
   * high < close
   * low > open
   * low > close
   * negative volume
   * negative traded_value
5. Handle missing adjusted_close.
6. Allow config options for excluding:

   * suspended symbols,
   * delisted symbols,
   * preferred shares,
   * SPACs,
   * ETFs,
   * extremely illiquid symbols,
   * extremely low-priced symbols.

Do not silently remove problematic rows without logging the decision.

---

## 5. Configuration

Create `configs/example.yaml`.

It must include:

```yaml
data:
  path: data/sample/synthetic_ohlcv.csv
  format: csv
  date_column: date
  symbol_column: symbol

universe:
  markets: ["KOSPI", "KOSDAQ"]
  min_traded_value_lookback: 20
  min_traded_value: 1000000000
  exclude_suspended: true
  exclude_delisted: false
  exclude_low_price_below: 1000

splits:
  train_start: "2010-01-01"
  train_end: "2018-12-31"
  validation_start: "2019-01-01"
  validation_end: "2022-12-31"
  final_holdout_start: "2023-01-01"
  final_holdout_end: "2025-12-31"

backtest:
  initial_cash: 100000000
  max_positions: 10
  position_size_pct: 0.10
  rebalance_frequency: daily
  signal_timing: close
  execution_timing: next_open
  allow_same_bar_execution: false

costs:
  commission_bps: 3
  sell_tax_bps: 0
  slippage_bps: 10
  cost_sensitivity_multipliers: [1, 2, 3]

liquidity:
  max_order_pct_of_avg_traded_value: 0.01
  avg_traded_value_lookback: 20

risk:
  max_position_pct: 0.10
  max_gross_exposure: 1.0
  stop_loss_pct: null
  take_profit_pct: null
  trailing_stop_atr_multiple: null

research:
  max_hypotheses: 100
  random_seed: 42
  min_trades: 100
  allow_final_holdout_during_research: false

validation_gates:
  min_cagr: 0.10
  min_sharpe: 0.80
  max_mdd: 0.25
  min_trade_count: 100
  max_turnover: null
  require_cost_2x_positive: true
  require_parameter_sensitivity_pass: true

report:
  output_dir: outputs/reports
  include_charts: true
```

Values may be changed, but all fields must be represented or documented.

---

## 6. Hypothesis Format

Implement a hypothesis spec in JSON or YAML.

Each hypothesis must include:

```yaml
id: H-001
idea: "20-day high breakout with volume surge may predict short-term momentum."
universe:
  markets: ["KOSPI", "KOSDAQ"]
  liquidity_filter:
    min_avg_traded_value: 1000000000
    lookback: 20
features:
  - adjusted_close
  - volume
  - traded_value
  - return_5d
  - high_20d
  - volume_ratio_20d
entry_rule:
  description: "Enter when adjusted close breaks above prior 20-day high and volume is at least 2x its 20-day average."
  expression: "close > prior_high_20d and volume_ratio_20d >= 2.0"
exit_rule:
  description: "Exit after 5 trading days or risk rule trigger."
  holding_period_days: 5
  stop_loss_pct: 0.05
  take_profit_pct: null
position_sizing:
  method: equal_weight
  max_position_pct: 0.10
  max_positions: 10
cost_model:
  commission_bps: 3
  sell_tax_bps: 0
  slippage_bps: 10
falsification:
  min_trades: 100
  min_validation_cagr: 0.10
  min_validation_sharpe: 0.80
  max_validation_mdd: 0.25
notes: []
```

The framework must validate the hypothesis before running it.

Invalid hypotheses must be rejected and logged.

---

## 7. Strategy Types to Support Initially

Implement at least several simple built-in strategy templates so the research loop can run without an external LLM.

Required built-in families:

1. Breakout with volume confirmation
2. Moving-average trend following
3. Short-term reversal
4. Volatility contraction breakout
5. Gap continuation or gap reversal
6. RSI mean reversion
7. Price-volume momentum
8. High traded-value momentum filter

Each generated hypothesis must instantiate one of these templates with explicit parameters.

Do not generate unlimited arbitrary Python code during the research loop unless sandboxing and review are implemented.

---

## 8. Feature Engineering Rules

All rolling features must be computed per symbol.

All signal features must be shifted where necessary so the signal only uses information available at the decision time.

Examples:

* A close-based signal at date T may execute no earlier than date T+1 open.
* A prior 20-day high used on date T must not include date T high if the strategy claims to know it before the close.
* A feature using the full dataset mean or standard deviation is forbidden unless computed expanding or rolling using only past data.
* Future returns may be computed only for evaluation labels, never for signal generation.

Create tests that would fail if lookahead is introduced.

---

## 9. Backtesting Rules

Implement a conservative backtester.

Required behavior:

1. Close-based signals execute at next available open.
2. Same-bar execution is forbidden by default.
3. Apply commission, sell tax placeholder/config, and slippage.
4. Support long-only strategies initially.
5. Support equal-weight position sizing.
6. Support max positions.
7. Support liquidity cap:

   * order value must not exceed a configured percentage of recent average traded value.
8. Support partial-fill placeholder or conservative rejection when liquidity is insufficient.
9. Track cash, positions, equity, orders, trades, and daily portfolio value.
10. Handle missing prices.
11. Handle suspended or untradable rows conservatively.
12. Do not assume a trade can occur at a price that was not available at the execution timestamp.

The backtester must output:

* equity curve
* drawdown curve
* order log
* trade log
* daily position snapshot or sufficient reconstruction data
* metrics summary

---

## 10. Metrics

Implement at least:

* total return
* CAGR
* annualized volatility
* Sharpe ratio
* Sortino ratio
* max drawdown
* Calmar ratio
* win rate
* average win
* average loss
* profit factor
* trade count
* exposure
* turnover
* average holding period
* benchmark-relative return if benchmark data is provided
* yearly returns
* monthly returns if feasible

Metrics must be deterministic and unit-tested.

Avoid division-by-zero failures.

Report insufficient data instead of producing misleading values.

---

## 11. Validation

The framework must split data chronologically:

1. Train
2. Validation
3. Final holdout

Rules:

* The research loop may use train and validation.
* The final holdout must not be used during hypothesis generation, parameter tuning, ranking, or strategy selection.
* The final holdout is evaluated only once for the selected candidate.
* If the selected candidate fails on final holdout, the final conclusion must say FAIL or NEEDS_MORE_RESEARCH.
* Do not go back and modify the strategy after seeing final holdout results.

Implement:

1. Walk-forward validation
2. Year-by-year performance breakdown
3. Cost sensitivity at 1x, 2x, and 3x configured costs
4. Parameter sensitivity checks
5. Minimum trade count check
6. Concentration check:

   * profit concentration by symbol
   * profit concentration by year
   * profit concentration by top trades
7. Optional bootstrap confidence intervals if feasible

---

## 12. Overfitting Controls

The system must explicitly account for repeated hypothesis testing.

Implement or stub with clear warnings:

* count of tested hypotheses
* count of rejected hypotheses
* count of passed train gates
* count of passed validation gates
* parameter search size
* fragility penalty
* turnover penalty
* low-trade-count penalty
* concentrated-profit penalty
* drawdown penalty

Include placeholders or approximate implementations for:

* Deflated Sharpe Ratio style adjustment
* White Reality Check style correction
* bootstrap resampling of trade or daily returns

If exact statistical implementation is not completed, the report must clearly label it as a placeholder and must not overstate statistical significance.

---

## 13. Critic Module

Implement a critic that reviews each hypothesis and result.

It must flag or reject:

1. Lookahead risk
2. Same-bar execution risk
3. Survivorship-bias risk
4. Final-holdout contamination
5. Too few trades
6. Illiquidity
7. Excessive turnover
8. Excessive drawdown
9. Profit concentration
10. Parameter fragility
11. Unrealistic execution
12. Missing cost assumptions
13. Inconsistent schema
14. Suspiciously high performance
15. Use of forbidden data

The critic must produce structured output:

```json
{
  "status": "pass|warn|reject",
  "flags": [
    {
      "severity": "low|medium|high",
      "code": "LOOKAHEAD_RISK",
      "message": "Signal uses same-day high before it would be known."
    }
  ],
  "summary": "Rejected due to lookahead risk."
}
```

Warnings and rejections must be logged.

---

## 14. Scoring

Do not rank strategies by raw return alone.

Implement a scoring function using:

* CAGR
* Sharpe
* Sortino
* max drawdown
* Calmar
* stability across years
* trade count
* turnover
* liquidity
* cost sensitivity
* parameter sensitivity
* concentration penalties

Recommended form:

```text
score =
  0.20 * normalized_CAGR
+ 0.20 * normalized_Sharpe
+ 0.15 * normalized_Calmar
+ 0.15 * normalized_stability
+ 0.10 * normalized_liquidity
+ 0.10 * normalized_cost_sensitivity
+ 0.10 * normalized_parameter_robustness
- turnover_penalty
- drawdown_penalty
- concentration_penalty
- low_trade_count_penalty
```

The exact implementation may differ, but it must be documented and deterministic.

---

## 15. Research Ledger

Implement a persistent research ledger using SQLite or JSONL.

Every experiment must be logged, including failures.

Log at least:

* hypothesis id
* timestamp
* random seed
* strategy family
* parameters
* universe filters
* data date range
* train metrics
* validation metrics
* final holdout metrics, only if evaluated
* pass/fail status
* pass/fail reason
* critic output
* cost assumptions
* tested hypothesis count
* code version or git hash if feasible
* artifact paths

The ledger must make it possible to reconstruct:

1. What was tested.
2. Why it passed or failed.
3. How many alternatives were tried before the selected strategy.
4. Whether the final holdout was accessed.

---

## 16. Research Loop

Implement a command:

```bash
python -m app.run_research --config configs/example.yaml
```

Expected behavior:

1. Load config.
2. Load local data.
3. Validate schema.
4. Generate or load candidate hypotheses.
5. Run one hypothesis at a time.
6. Validate each hypothesis.
7. Critique each result.
8. Log every result.
9. Maintain a candidate pool.
10. Stop when max_hypotheses is reached or configured gates are satisfied.
11. Save candidate artifacts.
12. Print a concise summary.

The loop must not evaluate final_holdout.

---

## 17. One-Hypothesis Runner

Implement a command:

```bash
python -m app.run_one_hypothesis --config configs/example.yaml --hypothesis path/to/hypothesis.yaml
```

Expected behavior:

1. Validate the hypothesis schema.
2. Run train and validation backtests.
3. Apply gates.
4. Run critic.
5. Log result.
6. Save artifacts.

Do not evaluate final_holdout unless explicitly configured for final evaluation mode.

---

## 18. Final Report

Implement a command:

```bash
python -m app.final_report --config configs/example.yaml
```

Expected behavior:

1. Read the ledger.
2. Select the best validated candidate using the pre-defined scoring function.
3. Evaluate final_holdout exactly once.
4. Generate a Markdown or HTML report.

The report must include:

* research objective
* data assumptions
* allowed and forbidden data
* schema summary
* train/validation/final_holdout date ranges
* total hypotheses tested
* rejected hypothesis count
* selected strategy
* strategy parameters
* train metrics
* validation metrics
* final holdout metrics
* equity curve data path
* drawdown data path
* yearly performance
* trade count
* turnover
* cost sensitivity
* parameter sensitivity
* critic flags
* overfitting controls
* limitations
* final conclusion: PASS, FAIL, or NEEDS_MORE_RESEARCH

The report must not imply live-trading readiness.

A PASS means only that the strategy is a candidate for paper trading.

---

## 19. Tests

Add pytest tests for:

1. Data schema validation
2. OHLC impossibility checks
3. Feature generation without lookahead
4. Rolling features computed per symbol
5. Next-bar execution
6. Same-bar execution prevention
7. Cost application
8. Slippage application
9. Liquidity cap behavior
10. Metric calculations
11. Drawdown calculation
12. Chronological split
13. Final-holdout access prevention
14. Hypothesis schema validation
15. Critic rejection behavior
16. Ledger logging
17. Research loop runs on synthetic data
18. Final report generation

All tests must pass with:

```bash
pytest
```

---

## 20. README Requirements

Update or create `README.md`.

It must explain:

1. What the project does.
2. What data is allowed.
3. What data is forbidden.
4. How to provide Korean OHLCV data.
5. Required schema.
6. How to run tests.
7. How to run one hypothesis.
8. How to run the research loop.
9. How to generate the final report.
10. Why final holdout must be evaluated only once.
11. Why this is not a live trading system.
12. Known limitations.

---

## 21. Sample Data

Create synthetic OHLCV data in:

```text
data/sample/synthetic_ohlcv.csv
```

The sample data must contain multiple symbols and enough dates to run:

* feature generation
* train split
* validation split
* final_holdout split
* at least several trades

Synthetic data does not need to be profitable.

Its purpose is to make the framework testable without external data.

---

## 22. Completion Criteria

The implementation is complete only when all of the following are true:

1. The project runs without internet access.
2. The project runs on included synthetic OHLCV data.
3. `pytest` passes.
4. `python -m app.run_research --config configs/example.yaml` runs successfully.
5. `python -m app.run_one_hypothesis --config configs/example.yaml --hypothesis <sample_hypothesis>` runs successfully.
6. `python -m app.final_report --config configs/example.yaml` generates a Markdown or HTML report.
7. Every experiment is logged.
8. Failed experiments are logged.
9. The final holdout is not used during the research loop.
10. The final report clearly states PASS, FAIL, or NEEDS_MORE_RESEARCH.
11. The README explains usage and limitations.
12. The code contains tests for leakage prevention and next-bar execution.
13. The implementation prefers correctness, reproducibility, and anti-overfitting safeguards over high backtest returns.

---

## 23. Completion Audit Required Before Marking Done

Before declaring the task complete, perform an audit.

The audit must check:

```bash
pytest
python -m app.run_research --config configs/example.yaml
python -m app.run_one_hypothesis --config configs/example.yaml --hypothesis configs/sample_hypothesis.yaml
python -m app.final_report --config configs/example.yaml
```

Also inspect:

* generated ledger file
* generated report file
* README
* config file
* sample data
* tests

Do not mark the goal as complete merely because files were created.

The goal is complete only if the repository actually runs end-to-end and the completion criteria above are satisfied.

If a requirement cannot be completed, leave a clear TODO in the code and mention it in the final summary.
