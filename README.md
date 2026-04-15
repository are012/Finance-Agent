# Finance Agent

Lean 기반 연구/백테스트와 KIS 주문 어댑터를 분리하고, 웹에서 차트와 백테스트를 바로 다룰 수 있게 만든 퀀트 워크스페이스입니다.

## 핵심 구조

- `quant/strategies/`: Lean 전략 템플릿
- `quant/research/`: yfinance 데이터 로더와 로컬 백테스트 엔진
- `quant/lean/`: Lean 프로젝트 스캐폴딩
- `quant/brokers/`: KIS 주문 어댑터
- `quant/runtime/`: 런타임 서비스와 실행 기록 저장
- `api/server.py`: FastAPI 엔드포인트
- `main.py`: CLI 엔트리포인트
- `index.html`: 차트, 전략 선택, 백테스트 결과를 보여주는 웹 UI

## 빠른 시작

Anaconda에서 새 환경을 만들어 사용하는 것을 기본 기준으로 합니다.

```bash
conda env create -f environment.yml
conda activate finance-agent
python3 main.py framework-info
python3 main.py list-strategies
python3 main.py run-backtest --strategy-key bollinger_reversion --ticker NVDA --param lookback_period=20 --param band_width=2.2
python3 main.py create-project --strategy-key sma_cross --ticker AAPL --param fast_period=10 --param slow_period=30
python3 main.py preview-order --ticker 005930 --side buy --quantity 1 --account-mode paper
python3 main.py serve-api --reload
```

이미 환경을 만든 뒤 수동으로 맞추고 싶다면 아래 방식도 가능합니다.

```bash
conda create -n finance-agent python=3.12 -y
conda activate finance-agent
pip install -r requirements.txt
```

## API

- `GET /api/healthz`
- `GET /api/quant/framework`
- `GET /api/quant/strategies`
- `GET /api/quant/chart-context`
- `GET /api/quant/runs`
- `POST /api/quant/backtests`
- `POST /api/quant/lean/projects`
- `GET /api/quant/runs/{run_id}`
- `POST /api/quant/kis/orders/preview`
- `POST /api/quant/kis/orders/submit`

## 웹 UI

`python3 main.py serve-api --reload` 후 `http://127.0.0.1:8000/`를 열면 아래 흐름을 바로 쓸 수 있습니다.

- 미국 주식과 한국 주식 차트 전환
- 여러 전략 카드 선택과 파라미터 조정
- 즉시 백테스트 실행과 equity curve 확인
- 최근 Lean 프로젝트 생성 이력 확인

## 전략 템플릿

- `bollinger_reversion`
- `buy_hold`
- `sma_cross`
- `ema_cross`
- `rsi_reversion`

## 주의

- Lean 로컬 실행과 데이터 준비는 별도로 필요합니다.
- 로컬 백테스트 데이터는 `yfinance` 일봉 데이터를 사용합니다.
- TradingView 차트 로딩을 위해 브라우저에서 외부 스크립트 접근이 가능해야 합니다.
- KIS 주문 제출은 환경변수와 토큰이 준비되어야 합니다.
- 기본 KIS 매퍼는 국내주식 현금주문 기준입니다. 해외주식, 신용, ETF/ETN, 파생 등은 별도 확장이 필요합니다.
- Anaconda 환경 이름은 기본적으로 `finance-agent`를 권장합니다.
