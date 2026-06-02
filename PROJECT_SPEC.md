# PROJECT_SPEC.md

# Chart-Only Korean Market Systematic Trading Research Framework

Version: 1.0  
Status: Implementation contract  
Scope: Research-only, local data only, no live trading

---

## 0. Mission

Build a reproducible Python research framework for Korean stock-market systematic trading using **only chart-derived data**.

The framework must support an agentic research loop that:

1. Generates one explicit trading hypothesis at a time.
2. Converts that hypothesis into a fully specified strategy.
3. Backtests the strategy with conservative execution assumptions.
4. Validates the strategy out-of-sample.
5. Critiques the strategy for leakage, overfitting, unrealistic execution, fragility, concentration, and data-quality issues.
6. Logs every experiment, including rejected and failed hypotheses.
7. Continues until the configured research budget is exhausted or until a candidate satisfies all validation gates.
8. Selects the best validated candidate using pre-defined scoring rules.
9. Evaluates the final holdout only once.
10. Produces a final report with a clear conclusion:
    - `PASS`: strategy is only a candidate for paper trading.
    - `FAIL`: no robust candidate was found.
    - `NEEDS_MORE_RESEARCH`: evidence is inconclusive.

This project is for research only. Do **not** implement live trading, broker integration, order placement, account login, real-money execution, API trading, or automated brokerage actions.

---

## 1. Non-Negotiable Constraints

### 1.1 Allowed Data

Only the following local data fields may be used:

- `date`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `adjusted_close`
- `volume`
- `traded_value`
- `market`
- `listing_status`, if available
- chart-derived indicators computed only from the fields above

Allowed chart-derived features include:

- simple returns
- log returns
- gap returns
- intraday range
- candle body size
- upper wick size
- lower wick size
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
- turnover-like proxies if computable from available fields
- VWAP-like approximations only when computable from OHLCV/traded value

### 1.2 Forbidden Data

Do not use:

- fundamentals
- financial statements
- earnings data
- revenue, profit, margin, debt, assets, valuation ratios
- analyst reports
- target prices
- news
- disclosures
- social media
- macroeconomic indicators
- investor-flow data
- foreign/institutional/retail net buying data
- order-book data unless explicitly provided as local chart data and enabled by config
- future returns in signal generation
- future highs/lows in signal generation
- current index membership applied backward in time
- current survivor universe applied backward in time
- any feature that cannot be known at the decision timestamp
- internet data during test runs
- live market data during tests

### 1.3 Anti-Goal

The goal is **not** to maximize backtest return at any cost.

The goal is to build a conservative research system that prefers:

- no lookahead bias,
- no final-holdout contamination,
- realistic execution assumptions,
- repeatable results,
- full experiment logging,
- robustness checks,
- risk-adjusted performance,
- transparent failure reporting.

A lower-return but robust strategy is preferred over a fragile high-return strategy.

---

## 2. Expected Project Structure

Recommended structure:

```text
.
├── README.md
├── PROJECT_SPEC.md
├── pyproject.toml
├── configs
│   ├── example.yaml
│   └── hypotheses
│       ├── momentum_20.yaml
│       ├── breakout_volume_20.yaml
│       └── reversal_rsi_5.yaml
├── data
│   ├── README.md
│   └── sample
│       └── synthetic_ohlcv.csv
├── app
│   ├── __init__.py
│   ├── run_research.py
│   ├── run_one_hypothesis.py
│   └── final_report.py
├── research
│   ├── __init__.py
│   ├── config.py
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
│   ├── test_liquidity.py
│   ├── test_metrics.py
│   ├── test_validation_split.py
│   ├── test_hypothesis_schema.py
│   ├── test_critic.py
│   ├── test_ledger.py
│   └── test_cli_end_to_end.py
└── outputs
    ├── ledger
    ├── reports
    └── artifacts
```

The structure may be adapted if the repository already has a reasonable layout, but all responsibilities must be clear, testable, and documented.

---

## 3. Technology Requirements

Use Python.

Prefer simple, reliable dependencies:

- `pandas`
- `numpy`
- `PyYAML`
- `pydantic` or `dataclasses`
- `pytest`
- `matplotlib`, only for optional report charts
- standard-library `sqlite3` or JSONL for the ledger

The project must run offline on included synthetic OHLCV data.

Do not require proprietary data, external APIs, internet access, brokerage credentials, or paid services to run tests.

---

## 4. Configuration Requirements

Create or update `configs/example.yaml` so that it contains all required configuration sections.

A valid example configuration should look like this:

```yaml
data:
  path: data/sample/synthetic_ohlcv.csv
  format: csv
  date_column: date
  symbol_column: symbol

universe:
  markets: ["KOSPI", "KOSDAQ"]
  min_traded_value_lookback: 20
  min_traded_value: 100000000
  exclude_suspended: true
  exclude_delisted: false
  exclude_low_price_below: 1000
  exclude_listing_statuses: ["suspended"]

splits:
  mode: date
  train_start: "2020-01-01"
  train_end: "2021-12-31"
  validation_start: "2022-01-01"
  validation_end: "2022-12-31"
  final_holdout_start: "2023-01-01"
  final_holdout_end: "2023-12-31"

backtest:
  initial_cash: 100000000
  max_positions: 10
  position_size_pct: 0.10
  rebalance_frequency: daily
  signal_timing: close
  execution_timing: next_open
  allow_same_bar_execution: false
  force_liquidate_at_end: true

costs:
  commission_bps: 3
  sell_tax_bps: 0
  slippage_bps: 10
  cost_sensitivity_multipliers: [1, 2, 3]

liquidity:
  max_order_pct_of_avg_traded_value: 0.01
  avg_traded_value_lookback: 20
  insufficient_liquidity_policy: reject

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
  built_in_hypotheses: true
  hypothesis_dir: configs/hypotheses

validation_gates:
  min_cagr: 0.10
  min_sharpe: 0.80
  max_mdd: 0.25
  min_trade_count: 100
  max_turnover: null
  require_cost_2x_positive: true
  require_parameter_sensitivity_pass: true
  max_top_trade_profit_share: 0.30
  max_top_symbol_profit_share: 0.40

report:
  output_dir: outputs/reports
  include_charts: true
  final_holdout_key: example-synthetic-holdout-v1
```

The exact values may differ, especially for synthetic data, but each field must be represented or documented.

---

## 5. Data Schema

Support local CSV and Parquet data.

Canonical OHLCV schema:

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
2. Reject forbidden or unknown columns unless explicitly allowed by config.
3. Convert `date` to datetime.
4. Convert numeric columns to numeric types.
5. Sort by `symbol`, then `date`.
6. Deduplicate duplicated `symbol/date` rows deterministically or reject them. The policy must be documented.
7. Reject or flag impossible OHLC rows:
   - `high < low`
   - `high < open`
   - `high < close`
   - `low > open`
   - `low > close`
   - price <= 0
   - negative volume
   - negative traded_value
8. Handle missing `adjusted_close` according to explicit policy.
9. Support filtering by market and listing status.
10. Log any row removal or rejection decision.

Do not silently clean data in a way that changes research results without logging.

---

## 6. Feature Engineering

All features must be computed per symbol.

All signal features must be computed using only information available at the decision timestamp.

Required features:

- `return_1`
- `log_return_1`
- `gap_return`
- `intraday_range`
- `candle_body`
- `upper_wick`
- `lower_wick`
- `typical_price`
- `vwap_proxy`, if computable
- moving averages
- moving-average distance
- momentum
- short-term reversal
- volatility
- ATR
- Bollinger Band upper/lower/middle
- RSI
- MACD
- prior high/low
- high breakout
- low breakdown
- volume moving average
- volume surge
- traded value moving average

Lookahead rules:

- A close-based signal at date `T` may execute no earlier than date `T+1` open.
- A prior high or prior low used at date `T` must not include date `T` high/low unless explicitly declared as a close-confirmed signal.
- Future returns may be computed only for evaluation labels, never for signal generation.
- Global normalization using the full dataset is forbidden.
- Expanding or rolling normalization is allowed only if it uses past and current information appropriately.

Tests must fail if future information is introduced into signal features.

---

## 7. Hypothesis Format

Support external hypothesis files in YAML or JSON.

Example hypothesis:

```yaml
id: H-001
name: 20-day breakout with volume confirmation
idea: "A close above the prior 20-day high combined with a volume surge may predict short-term momentum."
strategy_family: breakout_volume
universe:
  markets: ["KOSPI", "KOSDAQ"]
  liquidity_filter:
    min_avg_traded_value: 100000000
    lookback: 20
features:
  - adjusted_close
  - volume
  - traded_value
  - prior_high_20
  - volume_surge_20
entry_rule:
  description: "Enter when close breaks above prior 20-day high and volume is at least 2x the 20-day average."
  expression: "close > prior_high_20 and volume_surge_20 >= 1.0"
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

Validation requirements:

1. Reject hypotheses using forbidden features.
2. Reject hypotheses with missing entry/exit rules.
3. Reject hypotheses with non-positive lookback or holding period.
4. Reject hypotheses that imply same-bar execution from close-based signals.
5. Reject hypotheses that require data outside the allowed chart-only scope.
6. Log invalid hypotheses to the ledger with a rejection reason.

---

## 8. Built-in Strategy Families

Implement built-in strategy families so the research loop can run without an external LLM.

Required families:

1. `breakout_volume`: breakout with volume confirmation
2. `ma_trend`: moving-average trend following
3. `short_reversal`: short-term reversal
4. `volatility_contraction_breakout`: volatility contraction followed by breakout
5. `gap_continuation`: gap continuation
6. `gap_reversal`: gap reversal
7. `rsi_mean_reversion`: RSI-based mean reversion
8. `price_volume_momentum`: price-volume momentum
9. `traded_value_momentum`: momentum with traded-value filter

Each built-in strategy must have explicit parameters and a deterministic signal generation path.

Do not generate arbitrary executable Python strategy code during the research loop unless a safe sandbox and review mechanism are implemented.

---

## 9. Backtesting Requirements

Implement a conservative long-only backtester.

Required behavior:

1. Close-based signals execute no earlier than the next available open.
2. Same-bar execution is forbidden by default.
3. Apply commission, sell tax, and slippage.
4. Support equal-weight position sizing.
5. Support max positions.
6. Support max position percentage.
7. Support max gross exposure.
8. Support liquidity cap:
   - order value must not exceed configured percentage of recent average traded value.
9. If liquidity is insufficient, apply the configured policy:
   - `reject`, or
   - `partial_fill`.
10. Support placeholders for limit-up/limit-down and suspended trading constraints.
11. Handle missing prices conservatively.
12. Track cash, positions, equity, orders, trades, and daily portfolio value.
13. Track turnover and exposure.
14. Support risk-rule placeholders:
   - stop loss,
   - take profit,
   - trailing stop.
15. Force liquidation at the final bar only if configured.

Backtester outputs:

- equity curve
- drawdown curve
- order log
- trade log
- daily position snapshot or reconstructable position data
- metrics summary
- rejected order log, if any

The backtester must not assume a trade can occur at a price that was not available at the execution timestamp.

---

## 10. Cost Model

Implement configurable cost model.

Required fields:

- commission bps
- sell tax bps
- slippage bps
- cost sensitivity multipliers

Required behavior:

1. Buy orders apply positive slippage.
2. Sell orders apply negative slippage.
3. Commission applies to both buy and sell.
4. Sell tax applies only to sell orders.
5. Cost sensitivity tests must run at 1x, 2x, and 3x or configured multipliers.

---

## 11. Metrics

Implement deterministic, unit-tested metrics.

Required metrics:

- total return
- CAGR
- annualized volatility
- Sharpe ratio
- Sortino ratio
- max drawdown
- Calmar ratio
- win rate
- average win
- average loss
- profit factor
- trade count
- exposure
- turnover
- average holding period
- benchmark-relative return if benchmark data is available
- yearly returns
- monthly returns if feasible

Rules:

- Avoid division-by-zero errors.
- Return explicit insufficient-data values where appropriate.
- Do not present meaningless metrics as strong evidence.

---

## 12. Validation

Split data chronologically into:

1. train
2. validation
3. final_holdout

Rules:

- Research loop may use train and validation.
- Research loop must not use final_holdout.
- Final holdout is evaluated only once after candidate selection.
- If final holdout fails, do not modify the strategy in the same research run.
- Any post-holdout modification must be treated as a new research cycle with a new holdout policy.

Required validation tools:

1. Walk-forward validation
2. Year-by-year performance breakdown
3. Cost sensitivity at configured multipliers
4. Parameter sensitivity checks
5. Minimum trade count check
6. Profit concentration by symbol
7. Profit concentration by year
8. Profit concentration by top trades
9. Bootstrap confidence interval placeholder or implementation
10. Market-regime breakdown placeholder, if a market regime label is not available

---

## 13. Overfitting Controls

The system must explicitly account for repeated hypothesis testing.

Required tracking:

- total tested hypotheses
- rejected hypotheses
- train-passed hypotheses
- validation-passed hypotheses
- parameter search size
- final candidate selection reason

Required penalties or warnings:

- fragility penalty
- turnover penalty
- low-trade-count penalty
- concentrated-profit penalty
- drawdown penalty
- cost-sensitivity penalty
- parameter-sensitivity penalty

Implement or stub with explicit warnings:

- Deflated Sharpe Ratio style adjustment
- White Reality Check style correction
- bootstrap resampling of daily returns or trades

If exact statistical implementation is not completed, label it clearly as a placeholder. Do not overstate statistical significance.

---

## 14. Critic Module

Implement a structured critic.

Output format:

```json
{
  "status": "pass|warn|reject",
  "flags": [
    {
      "severity": "low|medium|high",
      "code": "LOOKAHEAD_RISK",
      "message": "Signal uses information unavailable at decision time."
    }
  ],
  "summary": "Rejected due to leakage risk."
}
```

The critic must flag or reject:

1. `LOOKAHEAD_RISK`
2. `SAME_BAR_EXECUTION_RISK`
3. `SURVIVORSHIP_BIAS_RISK`
4. `FINAL_HOLDOUT_CONTAMINATION`
5. `TOO_FEW_TRADES`
6. `ILLIQUID_EXECUTION`
7. `EXCESSIVE_TURNOVER`
8. `EXCESSIVE_DRAWDOWN`
9. `PROFIT_CONCENTRATION`
10. `PARAMETER_FRAGILITY`
11. `MISSING_COST_ASSUMPTION`
12. `SUSPICIOUSLY_HIGH_PERFORMANCE`
13. `FORBIDDEN_DATA`
14. `SCHEMA_INCONSISTENCY`
15. `UNREALISTIC_EXECUTION`

Warnings and rejections must be logged.

---

## 15. Scoring

Do not rank strategies by raw return alone.

Scoring should use:

- CAGR
- Sharpe
- Sortino
- max drawdown
- Calmar
- yearly stability
- trade count
- turnover
- liquidity
- cost sensitivity
- parameter sensitivity
- concentration penalties

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

The exact formula may differ, but it must be deterministic and documented.

`PASS` candidates should rank above `NEEDS_MORE_RESEARCH` candidates unless explicitly configured otherwise.

---

## 16. Research Ledger

Implement persistent logging using SQLite or JSONL.

Every experiment must be logged, including failures and invalid hypotheses.

Log at least:

- experiment id
- timestamp
- hypothesis id
- full hypothesis spec
- strategy family
- parameters
- random seed
- universe filters
- data path
- data hash, if feasible
- config snapshot
- git hash, if feasible
- train date range
- validation date range
- final holdout date range, but not final holdout metrics during research
- train metrics
- validation metrics
- final holdout metrics only during final report/evaluation
- trade count
- turnover
- cost assumptions
- cost sensitivity results
- parameter sensitivity results
- concentration results
- critic output
- pass/fail status
- pass/fail reason
- used_final_holdout flag
- artifact paths

The ledger must make it possible to reconstruct:

1. What was tested.
2. Why it passed or failed.
3. How many alternatives were tried.
4. Whether the final holdout was accessed.
5. Which config and data produced the result.

---

## 17. Research Loop CLI

Implement:

```bash
python -m app.run_research --config configs/example.yaml --output-dir outputs
```

Required behavior:

1. Load config.
2. Load local data.
3. Validate schema.
4. Apply universe filters.
5. Generate or load candidate hypotheses.
6. Run one hypothesis at a time.
7. Validate each hypothesis schema.
8. Backtest on train.
9. Backtest on validation.
10. Run validation checks.
11. Run critic.
12. Score the candidate.
13. Log every result.
14. Save artifacts.
15. Stop when max hypotheses is reached or configured gates are satisfied.
16. Do not evaluate final_holdout.
17. Print a concise summary.

If a hypothesis is invalid, log it and continue unless configured to fail fast.

---

## 18. One-Hypothesis CLI

Implement:

```bash
python -m app.run_one_hypothesis --config configs/example.yaml --hypothesis configs/hypotheses/momentum_20.yaml
```

Required behavior:

1. Load config.
2. Load and validate the hypothesis file.
3. Load local data.
4. Generate features.
5. Run train and validation backtests.
6. Apply validation gates.
7. Run critic.
8. Log result.
9. Save artifacts.
10. Do not evaluate final_holdout unless explicitly called in final-evaluation mode.

---

## 19. Final Report CLI

Implement:

```bash
python -m app.final_report --config configs/example.yaml --ledger outputs/ledger/experiments.jsonl --output-dir outputs/reports
```

Required behavior:

1. Read the ledger.
2. Select the best validated candidate using the scoring function.
3. Evaluate final_holdout exactly once.
4. Write a lock file for that holdout evaluation.
5. Reuse the locked result on future runs instead of re-evaluating holdout.
6. Generate Markdown and JSON reports.

The final report must include:

- research objective
- data assumptions
- allowed and forbidden data
- schema summary
- train/validation/final_holdout date ranges
- total hypotheses tested
- rejected hypothesis count
- selected strategy
- selected strategy parameters
- train metrics
- validation metrics
- final holdout metrics
- equity curve artifact path
- drawdown artifact path
- yearly results
- trade count
- turnover
- exposure
- cost sensitivity
- parameter sensitivity
- concentration analysis
- critic flags
- overfitting controls
- limitations
- final conclusion: `PASS`, `FAIL`, or `NEEDS_MORE_RESEARCH`

The report must not imply live-trading readiness.

A `PASS` means only that the strategy is a candidate for paper trading.

---

## 20. Sample Data

Create synthetic OHLCV data at:

```text
data/sample/synthetic_ohlcv.csv
```

Requirements:

1. Multiple symbols.
2. Enough dates to support train, validation, and final_holdout splits.
3. Enough rows to compute rolling features.
4. At least several possible trades.
5. Include `market` and `listing_status` columns.
6. No external data dependency.

Synthetic data does not need to be profitable. Its purpose is testability.

---

## 21. Tests

Add or update pytest tests for:

1. Data schema validation
2. OHLC impossibility checks
3. Forbidden column rejection
4. Feature generation without lookahead
5. Rolling features computed per symbol
6. Next-bar execution
7. Same-bar execution prevention
8. Cost application
9. Slippage application
10. Sell tax application
11. Liquidity cap behavior
12. Partial-fill or reject behavior
13. Metric calculations
14. Drawdown calculation
15. Chronological split
16. Final-holdout access prevention during research
17. Hypothesis schema validation
18. Invalid hypothesis logging
19. Critic structured flag behavior
20. Ledger logging
21. Scoring penalties
22. Research loop runs on synthetic data
23. One-hypothesis CLI runs on sample YAML
24. Final report generation
25. Holdout lock/reuse behavior

All tests must pass with:

```bash
pytest
```

---

## 22. README Requirements

Update README.md.

It must explain:

1. What the project does.
2. That it is research-only.
3. That it does not perform live trading.
4. What data is allowed.
5. What data is forbidden.
6. Required data schema.
7. How to provide Korean OHLCV data.
8. How to run tests.
9. How to run one hypothesis.
10. How to run the research loop.
11. How to generate the final report.
12. Why the final holdout must be evaluated only once.
13. How to interpret `PASS`, `FAIL`, and `NEEDS_MORE_RESEARCH`.
14. Known limitations.

---

## 23. Completion Criteria

The implementation is complete only when all of the following are true:

1. The project runs without internet access.
2. The project runs on included synthetic OHLCV data.
3. `pytest` passes.
4. `python -m app.run_research --config configs/example.yaml --output-dir outputs` runs successfully.
5. `python -m app.run_one_hypothesis --config configs/example.yaml --hypothesis configs/hypotheses/momentum_20.yaml` runs successfully.
6. `python -m app.final_report --config configs/example.yaml --ledger outputs/ledger/experiments.jsonl --output-dir outputs/reports` runs successfully.
7. Every experiment is logged.
8. Failed experiments are logged.
9. Invalid hypotheses are logged.
10. The final holdout is not used during the research loop.
11. The final report clearly states `PASS`, `FAIL`, or `NEEDS_MORE_RESEARCH`.
12. The README explains usage and limitations.
13. The code contains tests for leakage prevention and next-bar execution.
14. The implementation prefers correctness, reproducibility, and anti-overfitting safeguards over high backtest returns.

---

## 24. Completion Audit Required Before Marking Done

Before declaring the task complete, run:

```bash
pytest
python -m app.run_research --config configs/example.yaml --output-dir outputs
python -m app.run_one_hypothesis --config configs/example.yaml --hypothesis configs/hypotheses/momentum_20.yaml
python -m app.final_report --config configs/example.yaml --ledger outputs/ledger/experiments.jsonl --output-dir outputs/reports
```

Then inspect:

- `outputs/ledger/experiments.jsonl`
- `outputs/artifacts/`
- `outputs/reports/final_report.md`
- `outputs/reports/final_report.json`
- `outputs/reports/holdout_*.json`
- `README.md`
- `configs/example.yaml`
- `configs/hypotheses/`
- `data/sample/synthetic_ohlcv.csv`
- tests

Do not mark complete merely because files were created.

The goal is complete only if the repository actually runs end-to-end and the completion criteria above are satisfied.

If a requirement cannot be completed, leave an explicit TODO in code or documentation and mention it in the final summary.
