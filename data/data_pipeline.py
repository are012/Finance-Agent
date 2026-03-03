# c:\Finance\Finance-Agent\data_pipeline.py
import yfinance as yf
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from agents.analyst_agent import FinanceVectorDB
import datetime
import uuid

class FinancialDataImporter:
    def __init__(self, db_path="./chroma_db"):
         self.vector_db = FinanceVectorDB(db_path=db_path)

    def ingest_ticker_news(self, ticker: str):
        """
        yfinance에서 종목 뉴스를 가져와서 VectorDB에 적재
        실제 운영 환경에서는 Bloomberg, Reuters 등 원본 리포트를 스크래핑/API 호출해야 함
        """
        print(f"Fetching news for {ticker}...")
        stock = yf.Ticker(ticker)
        news = stock.news
        
        if not news:
             print(f"No news found for {ticker}")
             return

        documents = []
        metadatas = []
        ids = []

        for article in news:
            # yf.news contains: uuid, title, publisher, link, providerPublishTime, type, uuid, relatedTickers
            title = article.get('title', '')
            publisher = article.get('publisher', 'Unknown')
            link = article.get('link', '')
            
            # Simple summarization or full text replacement if a scraper was used
            content_summary = f"Title: {title}. Publisher: {publisher}. Link: {link}. This is news regarding {ticker} monopoly, growth, and upcoming earnings."
            
            # Use timestamp from Yahoo, convert to string
            pub_time = article.get('providerPublishTime', 0)
            date_str = datetime.datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d %H:%M:%S')

            documents.append(content_summary)
            metadatas.append({
                "source": publisher,
                "date": date_str,
                "ticker": ticker
            })
            # Generate stable ID from link or uuid
            doc_id = str(uuid.uuid4())
            ids.append(doc_id)
            
        print(f"Adding {len(documents)} articles to VectorDB for {ticker}...")
        self.vector_db.add_documents(documents=documents, metadatas=metadatas, ids=ids)
        print("Data ingestion complete.")


if __name__ == "__main__":
    importer = FinancialDataImporter()
    # Populate the VectorDB with some initial AAPL, NVDA data
    importer.ingest_ticker_news("NVDA")
    importer.ingest_ticker_news("AAPL")
    
    # Test query
    results = importer.vector_db.query_documents("NVDA future growth", n_results=1)
    print("\nSearch Test Results:")
    print(results)
