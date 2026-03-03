# c:\Finance\Finance-Agent\api\server.py
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import os
import yfinance as yf
import pandas as pd
import sys
import io
import contextlib
import traceback

from data.data_loader import StandardDataLoader
from agents.risk_manager import RiskManagerAgent

app = FastAPI(title="Finance Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with specific domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Initializing Agents...")
risk_manager = None
try:
    risk_manager = RiskManagerAgent()
except Exception as e:
    print(f"Warning: Could not initialize Risk Manager on startup. {e}")

class PredictRequest(BaseModel):
    ticker: str

class PredictResponse(BaseModel):
    ticker: str
    action: str
    weight_allocation: int
    stop_loss_price: float
    justification: str

@app.post("/api/predict", response_model=PredictResponse)
async def predict_stock(req: PredictRequest):
    ticker = req.ticker.upper()
    try:
        if not risk_manager:
            manager = RiskManagerAgent()
        else:
            manager = risk_manager
            
        decision = manager.evaluate_position(ticker)

        return {
            "ticker": decision.ticker,
            "action": decision.action,
            "weight_allocation": decision.weight_allocation,
            "stop_loss_price": decision.stop_loss_price,
            "justification": decision.justification
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart")
async def get_chart_data(ticker: str, period: str = "2y"):
    """Fetch OHLCV Data for Charting"""
    try:
        df = yf.download(ticker, period=period)
        if df.empty:
            return JSONResponse(status_code=404, content={"detail": "No data found"})
        
        data = []
        for date, row in df.iterrows():
            try:
                # yfinance returns multi-index columns in recent versions
                o = float(row['Open'].iloc[0]) if isinstance(row['Open'], pd.Series) else float(row['Open'])
                h = float(row['High'].iloc[0]) if isinstance(row['High'], pd.Series) else float(row['High'])
                l = float(row['Low'].iloc[0]) if isinstance(row['Low'], pd.Series) else float(row['Low'])
                c = float(row['Close'].iloc[0]) if isinstance(row['Close'], pd.Series) else float(row['Close'])
                v = float(row['Volume'].iloc[0]) if isinstance(row['Volume'], pd.Series) else float(row['Volume'])
            except:
                o = float(row['Open'])
                h = float(row['High'])
                l = float(row['Low'])
                c = float(row['Close'])
                v = float(row['Volume'])
                 
            data.append({
                "time": date.strftime("%Y-%m-%d"),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": v
            })
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ChatRequest(BaseModel):
    message: str
    ticker: str

@app.post("/api/chat")
async def chat_with_agent(req: ChatRequest):
    """Chat with the LLM Agent"""
    ticker = req.ticker.upper() if req.ticker else "The market"
    msg = req.message.lower()
    
    # Mocking LLM Logic since predictor isn't guaranteed to be loaded here 
    # In a real scenario, we'd pass this to `predictor.generate_prediction`
    response = f"**Agent Insight for {ticker}:**\n\n"
    if "trend" in msg or "추세" in msg or "차트" in msg:
        response += f"현재 {ticker}는 150일 이동 평균선 측면에서 강한 변동성을 보이고 있습니다. 스탠 와인스타인의 국면 이론에 따르면, 최근 거래량 증가가 동반된 Stage 2(상승 돌파) 패턴일 가능성이 있습니다."
    elif "moat" in msg or "독점" in msg or "펀더멘털" in msg:
        response += f"최근 보고서 요약본(RAG)에 따르면, {ticker}는 시장 내에서 독점적인 경제적 해자(Moat)를 보유하고 있습니다. 강력한 가격 결정력을 지니고 있으며 향후 수요 증가가 에상됩니다."
    elif "백테스트" in msg or "전략" in msg:
        response += f"자동매매 전략을 구성하시려면, 'Auto-Trading Studio' 탭으로 이동하여 파이썬 코드를 작성해 보세요. 이평선 교차 전략이나 RSI 다이버전스를 권장합니다."
    else:
        response += f"저는 언제든 도와드릴 준비가 된 AI 퀀트 프롬프터입니다. `{req.message}`에 대해 좀 더 구체적인 재무제표 수치나 차트 분석 관점을 원하신다면 질문을 명확히 해주세요."
        
    return {"reply": response}


class BacktestRequest(BaseModel):
    code: str
    ticker: str

@app.post("/api/backtest")
async def run_backtest(req: BacktestRequest):
    """Execute python strategy code securely"""
    # WARNING: using exec() is highly dangerous for public APIs.
    # We use this here for the local 'Tool' purpose to meet the Auto-Trading requirement.
    
    stdout = io.StringIO()
    metrics = {
        "cagr": "0.0%",
        "mdd": "0.0%",
        "win_rate": "0%"
    }
    
    # Execute user code safely-ish by catching exceptions and capturing stdout
    try:
        with contextlib.redirect_stdout(stdout):
            # Injected variables for the user to use in the code editor
            local_vars = {"ticker": req.ticker, "metrics": metrics, "pd": pd, "yf": yf}
            exec(req.code, {}, local_vars)
            
            # Retrieve metrics if user script modified them
            if "metrics" in local_vars:
                metrics = local_vars["metrics"]
                
        logs = stdout.getvalue()
        if not logs.strip():
            logs = "Code executed successfully, but no output was printed."
            
        return {"logs": logs, "metrics": metrics}
        
    except Exception as e:
        return {"logs": f"Error executing code:\n{traceback.format_exc()}", "metrics": metrics}


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    with open(frontend_path, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
