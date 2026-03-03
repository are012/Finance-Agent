# c:\Finance\Finance-Agent\risk_manager.py
from analyst_agent import AnalystAgent
from chartist_agent import ChartistAgent
from pydantic import BaseModel, Field

# Define an output schema for XAI report
class PositionDecision(BaseModel):
    ticker: str
    action: str = Field(description="Strong Buy, Buy, Hold, Sell, Strong Sell")
    weight_allocation: int = Field(description="Percentage 0 to 100")
    stop_loss_price: float = Field(description="Price to stop loss")
    justification: str = Field(description="Combined Fundamental and Technical explanation")

class RiskManagerAgent:
    def __init__(self):
        self.analyst = AnalystAgent()
        self.chartist = ChartistAgent()
        
    def evaluate_position(self, ticker: str) -> PositionDecision:
        """
        Analyst(펀더멘털)와 Chartist(기술적) 에이전트의 결과를 종합하여 최종 결정
        """
        print(f"--- Analyzing {ticker} ---")
        
        # 1. 펀더멘털 분석 실행 (Hegemony Score 획득)
        fundamental_analysis = self.analyst.analyze_fundamentals(ticker)
        hegemony = fundamental_analysis.get('Hegemony_Score', 0)
        moat_score = fundamental_analysis.get('Moat_Score', 0)
        growth_score = fundamental_analysis.get('Growth_Score', 0)
        moat_reason = fundamental_analysis.get('Moat_Reason', '')
        growth_reason = fundamental_analysis.get('Growth_Reason', '')
        
        print(f"[Analyst] Hegemony Score: {hegemony} (Moat: {moat_score}, Growth: {growth_score})")

        # 2. 기술적 분석 실행 (Stage 확인)
        technical_analysis = self.chartist.analyze(ticker)
        stage = technical_analysis.get('Stage', 0)
        trend = technical_analysis.get('Trend_Desc', '')
        signal = technical_analysis.get('Signal', 'Hold')
        close_price = technical_analysis.get('Close_Price', 0)
        ma_150 = technical_analysis.get('MA_150', 0)
        vol_ratio = technical_analysis.get('Breakout_Volume_Ratio', 0)
        
        print(f"[Chartist] Stage: {stage} ({trend}), Signal: {signal}, MA: {ma_150}, Vol Ratio: {vol_ratio}")

        # 3. 매트릭스 기반 의사결정 규칙 (Risk Management Logic)
        action = "Hold"
        weight_allocation = 0
        stop_loss_price = 0.0
        justification = ""
        
        # Rule 1: Strong Buy
        # 높은 헤게모니 점수 + 좋은 기술적 위치 (Stage 2 상승세 또는 돌파 초입)
        if hegemony >= 70 and (stage == 2 or signal == "Buy"):
            action = "Strong Buy"
            weight_allocation = 100
            justification = f"{ticker} exhibits excellent fundamental dominance (Hegemony: {hegemony}). Technically, it is in {trend} with a volume ratio of {vol_ratio}x. This confirms a Stage 2 expansion. Full allocation recommended."
            stop_loss_price = ma_150 * 0.95 # 손절은 MA_150을 하향 돌파(5% 버퍼)할 경우
            
        # Rule 2: Hold (Partial Taking Profit)
        # 높은 헤게모니이나 시장/차트가 고점(Stage 3)
        elif hegemony >= 70 and stage == 3:
             action = "Hold"
             weight_allocation = 50 # 비중 축소
             justification = f"Fundamentals remain strong (Hegemony: {hegemony}), but technicals show {trend} indicating potential distribution. Reduce position by half."
             stop_loss_price = ma_150 # 이평선 지지 확인
             
        # Rule 3: Ignore (False Breakout Protection)
        # 약한 펀더멘털이나 차트상 돌파가 보이는 경우 (속임수 시그널 필터링)
        elif hegemony < 50 and (stage == 2 or signal == "Buy"):
            action = "Ignore"
            weight_allocation = 0
            justification = f"Despite technical {trend}, the underlying fundamentals are weak (Hegemony: {hegemony}). Avoiding potential false breakout (Whipsaw)."
            stop_loss_price = close_price * 0.90
            
        # Rule 4: Strong Sell
        # 모든 조건 상관 없이 4국면 하락 시 전량 매도
        elif stage == 4 or signal == "Sell" or signal == "Sell/Short":
            action = "Strong Sell"
            weight_allocation = 0
            justification = f"Technicals show {trend} and price is below 150-day moving average ({ma_150}). Exiting all positions regardless of fundamentals."
            stop_loss_price = close_price # 즉각 시장가 매도
            
        else:
             action = "Watch"
             weight_allocation = 0
             justification = f"Waiting for clearer signal. Current: Hegemony={hegemony}, Stage={stage} ({trend})."
             stop_loss_price = ma_150 * 0.9

        # Construct explanation for XAI reporting
        full_justification = (
            f"**Decision Summary:** {action} with {weight_allocation}% allocation.\n"
            f"**Fundamental Moat/Growth Context:** {moat_reason} | {growth_reason}\n"
            f"**Technical Justification:** {justification}"
        )
        
        return PositionDecision(
            ticker=ticker,
            action=action,
            weight_allocation=weight_allocation,
            stop_loss_price=round(stop_loss_price, 2),
            justification=full_justification
        )


if __name__ == "__main__":
    manager = RiskManagerAgent()
    
    # Needs LLM config and VectorDB docs initialized to work perfectly, 
    # but provides the structure.
    print("Testing Risk Manager on NVDA...")
    # NOTE: In reality, LLM response will be blank until docs are added and engine is mapped
    # decision = manager.evaluate_position("NVDA") 
    # print(decision)
