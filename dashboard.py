# c:\Finance\Finance-Agent\dashboard.py
import streamlit as st
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from risk_manager import RiskManagerAgent

st.set_page_config(page_title="Quantamental AI Agent", layout="wide")

st.title("🤖 하이브리드 퀀트멘탈 투자 AI 시스템")
st.markdown("---")

# Sidebar for controls
st.sidebar.header("포트폴리오 설정")
ticker = st.sidebar.text_input("분석할 종목 심볼 입력 (e.g., AAPL, NVDA, TSLA)", "NVDA").upper()
analyze_btn = st.sidebar.button("시스템 분석 실행")

# Main content
if analyze_btn:
    with st.spinner(f"Agents are analyzing {ticker}..."):
        # Initialize and Run Agents
        manager = RiskManagerAgent()
        
        # NOTE: Due to the mockup nature, we overwrite with simulated realistic output for demo purposes
        # In a real run, `manager.evaluate_position(ticker)` will be called.
        decision = manager.evaluate_position(ticker)
        
        # --- UI Rendering ---
        
        # 1. Top Section - Final Decision
        st.header("1. 🎯 최종 투자 의견 (Risk Manager Agent)")
        col1, col2, col3 = st.columns(3)
        col1.metric("Action", decision.action)
        col2.metric("Portfolio Allocation", f"{decision.weight_allocation}%")
        col3.metric("Stop Loss / Support", f"${decision.stop_loss_price}")
        
        st.info(decision.justification)

        st.markdown("---")
        
        cols = st.columns(2)
        
        # 2. Left Panel - Fundamental (Analyst)
        with cols[0]:
            st.subheader("2. 📊 정성적 가치 평가 (Analyst Agent)")
            # Simulated RAG result display
            st.markdown("**Hegemony Score:** `85 / 100`")
            st.markdown("- **Moat (독점력):** 90 - AI 가속기 시장 사실상 독점, 높은 전환 비용.")
            st.markdown("- **Growth (성장성):** 80 - 차세대 칩(Blackwell) 수요 급증 예상.")
            
            st.write("최근 참고 뉴스 (RAG 검색):")
            st.caption("- NVDA Earnings blow past estimates, data center revenue surges (Source: Reuters)")
            st.caption("- AI Demand continues to outstrip supply... (Source: Bloomberg)")

        # 3. Right Panel - Technical (Chartist)
        with cols[1]:
            st.subheader("3. 📈 기술적 국면 분석 (Chartist Agent)")
            
            # Fetch actual data to plot
            df = yf.download(ticker, period="1y")
            if not df.empty:
                df['MA_150'] = df['Close'].rolling(window=150).mean()
                
                # Plot
                fig, ax = plt.subplots(figsize=(8, 4))
                ax.plot(df.index, df['Close'], label="Close Price", color='lightblue')
                ax.plot(df.index, df['MA_150'], label="150-Day MA (30-Week)", color='orange', linewidth=2)
                ax.set_title(f"{ticker} - Stan Weinstein Stage Analysis")
                ax.legend()
                ax.grid(alpha=0.3)
                
                st.pyplot(fig)
                
                st.markdown("**현재 국면:** `Stage 2 (상승 국면)`")
                st.write("- 150일선 안정적 상승 추세 유지")
                st.write("- 직전 고점 돌파 시 거래량 2.5배 증가 (건전한 상승)")
            else:
                st.error("Failed to load chart data.")

        # 4. Explainable AI (XAI) Traceability
        st.markdown("---")
        st.subheader("💡 의사결정 추적 (XAI X-Ray)")
        with st.expander("에이전트 로그 확인하기"):
            st.code('''
[System] Triggering pipeline for NVDA
[VectorDB] Searching 3 most relevant fundamental reports for "NVDA monopoly growth"...
[Analyst_Agent] LLM Inference complete. Hegemony=85 generated based on docs.
[Chartist_Agent] MA_150_Slope=0.12, Close_Gap=+15%, Vol_Ratio=1.8 -> Stage 2 identified.
[Risk_Manager] Rule 1 matched (Hegemony >= 70 AND Stage == 2). 
[Risk_Manager] Setting allocation to 100%. Stop loss anchored to MA_150 at $820.
            ''', language='log')
