# c:\Finance\Finance-Agent\main.py
import time
import schedule
from datetime import datetime
from data_loader import StandardDataLoader
from llm_engine import QwenPredictor

# Configuration
TICKER = "AAPL" # Change to target ticker (e.g., TSLA, NVDA, KRX codes like 005930.KS)
MODEL_ID = "Qwen/Qwen3.5-9B" # Ensure you have requested access / correct repo name on HF
CHECK_INTERVAL_HOURS = 4

class TradingBot:
    def __init__(self):
        self.data_loader = StandardDataLoader(ticker=TICKER)
        self.predictor = None # Lazy load to save resources if testing
        
    def initialize_llm(self):
        if self.predictor is None:
            self.predictor = QwenPredictor(model_name=MODEL_ID, use_4bit=True)

    def run_prediction_cycle(self):
        print(f"\n--- Starting Prediction Cycle for {TICKER} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        
        try:
            # 1. Fetch latest data
            print("Fetching latest data (Stock, News, SNS)...")
            context = self.data_loader.compile_all_data()
            print("Data fetching complete. Analyzing...")
            
            # 2. Init LLM
            self.initialize_llm()
            
            # 3. Generate Prediction
            prediction = self.predictor.generate_prediction(TICKER, context)
            
            # 4. Save Prediction Result
            self.save_result(context, prediction)
            print("Prediction Cycle Complete.\n")
            
        except Exception as e:
            print(f"Error during prediction cycle: {e}")

    def save_result(self, context, prediction):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"prediction_{TICKER}_{timestamp}.md"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# Financial Prediction Report - {TICKER}\n")
            f.write(f"**Date/Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## 1. Input Data Context\n```text\n")
            f.write(context)
            f.write("\n```\n\n")
            f.write("## 2. LLM Analysis & Prediction\n")
            f.write(prediction)
            
        print(f"Saved report to {filename}")

def main():
    bot = TradingBot()
    
    # Run once immediately
    bot.run_prediction_cycle()
    
    # Schedule repeating tasks
    schedule.every(CHECK_INTERVAL_HOURS).hours.do(bot.run_prediction_cycle)
    
    print(f"Bot scheduled to run every {CHECK_INTERVAL_HOURS} hours. Press Ctrl+C to exit.")
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
