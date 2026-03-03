# c:\Finance\Finance-Agent\server.py
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os

from data_loader import StandardDataLoader
from llm_engine import QwenPredictor

app = FastAPI(title="Finance Agent API")

# Initialize LLM globally (Lazy loading can be used, but for API we usually keep it hot)
print("Initializing LLM...")
# NOTE: In a real production environment with 9B model, initialization might take a minute.
predictor = None
try:
    predictor = QwenPredictor(model_name="Qwen/Qwen3.5-9B", use_4bit=True)
except Exception as e:
    print(f"Warning: Could not load LLM on startup. {e}")

class PredictRequest(BaseModel):
    ticker: str

class PredictResponse(BaseModel):
    ticker: str
    context: str
    prediction: str

@app.post("/api/predict", response_model=PredictResponse)
async def predict_stock(req: PredictRequest):
    if not predictor:
        raise HTTPException(status_code=503, detail="LLM Model is not initialized or currently loading.")
        
    ticker = req.ticker.upper()
    try:
        # Load Data
        loader = StandardDataLoader(ticker=ticker)
        context = loader.compile_all_data()

        # Predict
        prediction = predictor.generate_prediction(ticker, context)

        return PredictResponse(
            ticker=ticker,
            context=context,
            prediction=prediction
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
