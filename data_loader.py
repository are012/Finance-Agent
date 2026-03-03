# c:\Finance\Finance-Agent\data_loader.py
import yfinance as yf
import feedparser
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta

class StandardDataLoader:
    def __init__(self, ticker="AAPL"):
        self.ticker = ticker
        self.stock = yf.Ticker(self.ticker)

    def get_stock_data(self, period="1mo"):
        """Fetches historical stock data and calculates basic indicators."""
        try:
            hist = self.stock.history(period=period)
            if hist.empty:
                return "No stock data found."
            
            # Calculate simple moving averages
            if len(hist) >= 5:
                hist['SMA_5'] = hist['Close'].rolling(window=5).mean()
            if len(hist) >= 20:
                hist['SMA_20'] = hist['Close'].rolling(window=20).mean()

            recent = hist.tail(5)
            data_str = "Recent 5 Days Stock Data:\n"
            for date, row in recent.iterrows():
                data_str += f"- {date.strftime('%Y-%m-%d')}: Open {row['Open']:.2f}, High {row['High']:.2f}, Low {row['Low']:.2f}, Close {row['Close']:.2f}, Vol {row['Volume']}\n"
            return data_str
        except Exception as e:
            return f"Error fetching stock data: {e}"

    def get_news(self, limit=5):
        """Fetches recent news from Yahoo Finance for the ticker."""
        try:
            news_items = self.stock.news
            if not news_items:
                return "No news found for the given ticker."
            
            news_str = "Latest News & Reports:\n"
            for item in news_items[:limit]:
                title = item.get('title', 'No Title')
                pub_time = item.get('providerPublishTime', None)
                if pub_time:
                    dt = datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d %H:%M')
                else:
                    dt = "Unknown Time"
                summary = item.get('summary', 'No Summary')
                news_str += f"- [{dt}] {title}: {summary}\n"
            return news_str
        except Exception as e:
            return f"Error fetching news: {e}"

    def get_sns_data(self, limit=5):
        """
        Fetches SNS/Community sentiment by parsing Google News RSS for the ticker
        as a proxy for broader social/media context. Can be expanded with X/Reddit APIs.
        """
        try:
            url = f"https://news.google.com/rss/search?q={self.ticker}+stock&hl=en-US&gl=US&ceid=US:en"
            feed = feedparser.parse(url)
            
            sns_str = "Community/Media Mentions:\n"
            if not feed.entries:
                return sns_str + "No recent mentions found.\n"
                
            for entry in feed.entries[:limit]:
                dt = entry.get('published', 'Unknown Time')
                title = entry.get('title', 'No Title')
                sns_str += f"- [{dt}] {title}\n"
            
            return sns_str
        except Exception as e:
            return f"Error fetching SNS data: {e}"

    def compile_all_data(self):
        """Compiles all data into a cohesive prompt context."""
        stock = self.get_stock_data()
        news = self.get_news()
        sns = self.get_sns_data()
        
        context = f"--- STOCK DATA ({self.ticker}) ---\n{stock}\n\n"
        context += f"--- LATEST NEWS & REPORTS ---\n{news}\n\n"
        context += f"--- SNS & COMMUNITY SENTIMENT ---\n{sns}\n"
        return context
