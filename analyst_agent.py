# c:\Finance\Finance-Agent\analyst_agent.py
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from langchain.prompts import PromptTemplate
from langchain_community.llms import OpenAI # Replace with Qwen if integrated
from llm_engine import LLMEngine # Assuming local Qwen 3.5 engine exists
from kiwipiepy import Kiwi
from rank_bm25 import BM25Okapi

class FinanceVectorDB:
    def __init__(self, db_path="./chroma_db"):
        self.client = chromadb.PersistentClient(path=db_path)
        # 1. Update Dense Retrieval Model -> Jina Embeddings v5 Text Small
        self.embedding_model = SentenceTransformer(
            'jinaai/jina-embeddings-v5-text-small', 
            trust_remote_code=True
        )
        self.collection = self.client.get_or_create_collection(name="finance_reports")
        
        # 2. Setup Sparse Retrieval (BM25 & Kiwi)
        self.kiwi = Kiwi()
        self.corpus = []
        self.ids = []
        self.bm25 = None
        
        self._load_and_build_bm25()

    def _tokenize(self, text):
        # 한국어 및 영어/숫자 형태소 분석을 통해 핵심 키워드 토큰만 추출
        # N(명사), V(동사군), S(기호/문자/외국어), M(수식언) 계열 사용
        tokens = self.kiwi.tokenize(text)
        return [t.form for t in tokens if t.tag.startswith(('N', 'V', 'S', 'M'))]

    def _load_and_build_bm25(self):
        existing_data = self.collection.get()
        if existing_data and existing_data['documents']:
            self.corpus = existing_data['documents']
            self.ids = existing_data['ids']
            
            tokenized_corpus = [self._tokenize(doc) for doc in self.corpus]
            if tokenized_corpus:
                self.bm25 = BM25Okapi(tokenized_corpus)

    def add_documents(self, documents, metadatas, ids):
        embeddings = self.embedding_model.encode(documents).tolist()
        self.collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        
        # Update BM25 corpus internally
        self.corpus.extend(documents)
        self.ids.extend(ids)
        
        # Rebuild BM25
        tokenized_corpus = [self._tokenize(doc) for doc in self.corpus]
        if tokenized_corpus:
            self.bm25 = BM25Okapi(tokenized_corpus)

    def query_documents(self, query_text, n_results=3, alpha=0.5):
        """
        Hybrid Search: alpha=1.0 (Dense만), alpha=0.0 (BM25만).
        """
        if not self.ids or self.bm25 is None:
            return {"documents": [], "metadatas": [], "ids": []}

        # 1. Dense Search Scores
        query_embedding = self.embedding_model.encode([query_text]).tolist()
        dense_results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=len(self.ids)  # Fetch all to compute proper scaling
        )
        
        dense_scores_map = {}
        if dense_results['ids'] and dense_results['ids'][0]:
            for doc_id, dist in zip(dense_results['ids'][0], dense_results['distances'][0]):
                # Convert L2 distance to Similarity using 1 / (1 + dist)
                dense_scores_map[doc_id] = 1.0 / (1.0 + dist)
        
        # 2. Sparse Search Scores (BM25)
        sparse_scores_map = {}
        tokenized_query = self._tokenize(query_text)
        bm25_scores = self.bm25.get_scores(tokenized_query)
        for doc_id, score in zip(self.ids, bm25_scores):
            sparse_scores_map[doc_id] = score
            
        # 3. Min-Max Scaling
        def min_max_dict(score_dict):
            vals = list(score_dict.values())
            if not vals: return {}
            min_v, max_v = min(vals), max(vals)
            if max_v == min_v: return {k: 0.5 for k in score_dict}
            return {k: (v - min_v) / (max_v - min_v) for k, v in score_dict.items()}
            
        norm_dense = min_max_dict(dense_scores_map)
        norm_sparse = min_max_dict(sparse_scores_map)
        
        hybrid_scores = []
        for doc_id in self.ids:
            s_dense = norm_dense.get(doc_id, 0.0)
            s_sparse = norm_sparse.get(doc_id, 0.0)
            final_score = (alpha * s_dense) + ((1.0 - alpha) * s_sparse)
            hybrid_scores.append((doc_id, final_score))
            
        # Sort descending by hybrid score
        hybrid_scores.sort(key=lambda x: x[1], reverse=True)
        top_k_ids = [doc_id for doc_id, _ in hybrid_scores[:n_results]]
        
        # 4. Fetch and sort documents
        final_results = self.collection.get(ids=top_k_ids)
        doc_idx_map = {id_: idx for idx, id_ in enumerate(final_results['ids'])}
        
        sorted_docs, sorted_meta, valid_ids = [], [], []
        for tgt_id in top_k_ids:
            if tgt_id in doc_idx_map:
                idx = doc_idx_map[tgt_id]
                sorted_docs.append(final_results['documents'][idx])
                sorted_meta.append(final_results['metadatas'][idx])
                valid_ids.append(tgt_id)

        return {
            "documents": [sorted_docs],
            "metadatas": [sorted_meta],
            "ids": [valid_ids]
        }

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
