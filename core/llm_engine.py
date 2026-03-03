# c:\Finance\Finance-Agent\llm_engine.py
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

class QwenPredictor:
    def __init__(self, model_name="Qwen/Qwen3.5-9B", use_4bit=True):
        """
        Initializes the Qwen model. 
        Uses 4-bit quantization by default to fit the 9B model in consumer GPUs (e.g., 8-12GB VRAM).
        """
        self.model_name = model_name
        print(f"Loading {model_name}...")
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            
            if use_4bit:
                from transformers import BitsAndBytesConfig
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                )
                self.model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    device_map="auto",
                    quantization_config=quantization_config,
                    trust_remote_code=True
                )
            else:
                self.model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    device_map="auto",
                    torch_dtype=torch.float16,
                    trust_remote_code=True
                )
            print("Model loaded successfully.")
        except Exception as e:
            print(f"Error loading model: {e}")
            raise e

    def build_prompt(self, ticker, context_data):
        system_prompt = (
            "You are an elite AI financial analyst. "
            "Your task is to analyze the provided stock data (prices, technicals), news reports, and community sentiment, "
            "and predict the short-term and medium-term price movement of the stock. "
            "Provide a clear, objective analysis, outline bullish and bearish factors, and conclude with a specific prediction."
        )
        
        user_prompt = f"Target Stock Ticker: {ticker}\n\nLatest Compiled Data:\n{context_data}\n\nPlease analyze the above data and provide your stock price prediction strategy."

        # Format prompt according to ChatML or standard instruction format (Qwen uses ChatML for instruct models usually)
        # Assuming the base or instruct model can process this standard format:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        return text

    def generate_prediction(self, ticker, context_data, max_new_tokens=1024):
        prompt = self.build_prompt(ticker, context_data)
        model_inputs = self.tokenizer([prompt], return_tensors="pt").to(self.model.device)
        
        print("Generating prediction...")
        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.3, # Low temp for analytical consistency
                top_p=0.9,
                do_sample=True,
                repetition_penalty=1.1
            )
        
        generated_ids = [
            output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]

        response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return response
