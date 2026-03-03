# c:\Finance\Finance-Agent\analyst_agent.py
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from langchain.prompts import PromptTemplate
from langchain_community.llms import OpenAI # Replace with Qwen if integrated
from llm_engine import LLMEngine # Assuming local Qwen 3.5 engine exists

class FinanceVectorDB:
    def __init__(self, db_path="./chroma_db"):
        self.client = chromadb.PersistentClient(path=db_path)
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        self.collection = self.client.get_or_create_collection(name="finance_reports")

    def add_documents(self, documents, metadatas, ids):
        embeddings = self.embedding_model.encode(documents).tolist()
        self.collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

    def query_documents(self, query_text, n_results=3):
        query_embedding = self.embedding_model.encode([query_text]).tolist()
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=n_results
        )
        return results

class AnalystAgent:
    def __init__(self, vector_db_path="./chroma_db"):
        self.db = FinanceVectorDB(db_path=vector_db_path)
        self.llm = LLMEngine() # Use the custom local LLM engine
        
    def analyze_fundamentals(self, ticker: str) -> dict:
        """
        RAG를 이용해 비정형 문서에서 헤게모니 스코어(독점력, 성장성) 추출
        """
        # 1. Retrieve related documents for the ticker
        query = f"What is the market monopoly, pricing power, and future growth of {ticker}?"
        retrieved_docs = self.db.query_documents(query, n_results=5)
        
        context = ""
        if retrieved_docs['documents']:
            context = "\n".join(retrieved_docs['documents'][0])
            
        # 2. Setup Prompt for LLM
        prompt_template = PromptTemplate(
            input_variables=["ticker", "context"],
            template="""
            You are a senior financial analyst. Based on the following recent news and reports, 
            analyze the company {ticker}'s market dominance (Moat) and future growth potential.
            
            Context:
            {context}
            
            Provide a JSON output with the following structure:
            {{
                "Moat_Score": <0-100 score based on pricing power, barriers to entry>,
                "Growth_Score": <0-100 score based on new markets, CAPEX, revenue growth>,
                "Moat_Reason": "<Brief explanation for Moat>",
                "Growth_Reason": "<Brief explanation for Growth>"
            }}
            """
        )
        
        prompt = prompt_template.format(ticker=ticker, context=context)
        
        # 3. Generate Analysis
        # Assuming LLMEngine has a .generate(prompt) method returning text
        response_text = self.llm.generate(prompt)
        
        # 4. Parse JSON (Simplified for now, add robust parsing later)
        import json
        try:
            # Try to extract json block if wrapped in markdown
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            else:
                 json_str = response_text.strip()
            analysis_result = json.loads(json_str)
            
            # Calculate composite Hegemony Score
            moat = analysis_result.get("Moat_Score", 50)
            growth = analysis_result.get("Growth_Score", 50)
            analysis_result["Hegemony_Score"] = (moat * 0.4) + (growth * 0.6)
            
            return analysis_result
            
        except Exception as e:
            print(f"Error parsing LLM response: {e}")
            return {
                "Hegemony_Score": 50,
                "Moat_Score": 50,
                "Growth_Score": 50,
                "Moat_Reason": "Analysis failed or insufficient data.",
                "Growth_Reason": "Analysis failed or insufficient data.",
                "Raw_Response": response_text
            }

if __name__ == "__main__":
    # Test initialization
    agent = AnalystAgent()
    print("Analyst Agent Initialized.")
