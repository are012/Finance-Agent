import yfinance as yf
import pandas as pd
import numpy as np

class ChartistAgent:
    def __init__(self):
        self.moving_average_period = 150 # 30 weeks roughly equals 150 trading days
        
    def fetch_data(self, ticker: str, period="2y"):
        """종목의 일봉 데이터를 yfinance로 가져옴"""
        df = yf.download(ticker, period=period)
        return df

    def calculate_indicators(self, df: pd.DataFrame):
        """기술적 지표 계산: 30주(150일) 이평선, 상대강도 (TODO: RS), 거래량 등"""
        df['MA_150'] = df['Close'].rolling(window=self.moving_average_period).mean()
        df['Volume_MA_50'] = df['Volume'].rolling(window=50).mean()
        
        # Calculate slope of MA to determine trend direction
        df['MA_150_Slope'] = (df['MA_150'] - df['MA_150'].shift(20)) / 20 # 20일간의 기울기
        
        return df

    def analyze_stage(self, df: pd.DataFrame) -> dict:
        """스탠 와인스타인의 4국면 모델 적용 (단순화된 휴리스틱 규칙)"""
        if len(df) < self.moving_average_period + 20: # Not enough data
            return {"Stage": 0, "Trend_Desc": "Insufficient Data", "Signal": "Hold"}

        # 최근 데이터 포인트 가져오기
        latest = df.iloc[-1]
        
        close_price = float(latest['Close'].iloc[0] if isinstance(latest['Close'], pd.Series) else latest['Close'])
        ma_150 = float(latest['MA_150'].iloc[0] if isinstance(latest['MA_150'], pd.Series) else latest['MA_150'])
        ma_slope = float(latest['MA_150_Slope'].iloc[0] if isinstance(latest['MA_150_Slope'], pd.Series) else latest['MA_150_Slope'])
        vol = float(latest['Volume'].iloc[0] if isinstance(latest['Volume'], pd.Series) else latest['Volume'])
        vol_ma = float(latest['Volume_MA_50'].iloc[0] if isinstance(latest['Volume_MA_50'], pd.Series) else latest['Volume_MA_50'])

        
        stage = 0
        trend_desc = "Unknown"
        signal = "Hold"
        
        # 1. 1국면 판단: MA 기울기가 완만하고 가격이 수렴 중
        if abs(ma_slope) < 0.05 and abs(close_price - ma_150)/ma_150 < 0.05:
            stage = 1
            trend_desc = "Bottom/Sideways (Stage 1)"
            signal = "Watch"
            
        # 2. 2국면 판단: 상승 추세 (MA 상승 & 주가가 MA 위)
        elif ma_slope > 0.05 and close_price > ma_150:
            stage = 2
            # 돌파(Breakout) 조건 검사: 최근 며칠 사이 MA를 상향 돌파했는가? (간략화)
            if vol > vol_ma * 1.5:
                 trend_desc = "Breakout into Stage 2 (Strong Bullish)"
                 signal = "Buy"
            else:
                 trend_desc = "Advancing (Stage 2)"
                 signal = "Hold/Buy"
                 
        # 3. 3국면 판단: 고점에서 수렴 (가격은 높으나 MA 상승세 둔화)
        elif abs(ma_slope) < 0.05 and close_price > ma_150 and vol > vol_ma * 1.5: # 캔들 변동성 추가 필요
            stage = 3
            trend_desc = "Topping/Distribution (Stage 3)"
            signal = "Take Profit/Watch"

        # 4. 4국면 판단: 하락 추세 (MA 하락 & 주가가 MA 아래)
        elif ma_slope < -0.05 and close_price < ma_150:
            stage = 4
            trend_desc = "Declining (Stage 4)"
            signal = "Sell/Short"
            
        else: # 예외 케이스 처리
            if close_price > ma_150:
                 trend_desc = "Above MA but Trend Unclear"
            else:
                 trend_desc = "Below MA but Trend Unclear"

        # 변동성 비율 계산
        breakout_vol_ratio = round(vol / vol_ma, 2) if vol_ma > 0 else 0

        return {
            "Stage": stage,
            "Trend_Desc": trend_desc,
            "Close_Price": round(close_price, 2),
            "MA_150": round(ma_150, 2),
            "Breakout_Volume_Ratio": breakout_vol_ratio,
            "Signal": signal
        }

    def analyze(self, ticker: str):
        df = self.fetch_data(ticker)
        df_indicators = self.calculate_indicators(df)
        analysis_result = self.analyze_stage(df_indicators)
        return analysis_result


if __name__ == "__main__":
    # Test initialization
    chartist = ChartistAgent()
    print("Testing AAPL...")
    result = chartist.analyze("AAPL")
    print(result)
