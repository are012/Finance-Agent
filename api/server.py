# c:\Finance\Finance-Agent\server.py
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os

from data.data_loader import StandardDataLoader
from agents.risk_manager import RiskManagerAgent

app = FastAPI(title="Finance Agent API")

# Add CORS so frontend can be hosted independently
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
    if False: # Dummy check
        pass
        
    ticker = req.ticker.upper()
    try:
        if not risk_manager:
            # Lazy load if failed previously
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

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    with open(frontend_path, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
