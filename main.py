import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model

# 🔹 모델 ID (llama-stack으로 받은 경로 또는 HF ID)
MODEL_ID = "C:\\Users\\jaewo\\.llama\\checkpoints\\Llama3.1-8B-Instruct"

# 🔹 QLoRA 핵심 설정 (4bit)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.float16,
)

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
tokenizer.pad_token = tokenizer.eos_token

print("Loading base model in 4bit (QLoRA)...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map="auto",
)

# 🔹 LoRA 설정 (학습은 안 하지만, QLoRA 구조 테스트용)
lora_config = LoraConfig(
    r=8,
    lora_alpha=16,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=["q_proj", "v_proj"],
)

model = get_peft_model(model, lora_config)

# 학습 파라미터 수 출력 (정상 여부 확인용)
model.print_trainable_parameters()

# 🔹 테스트 프롬프트
prompt = """
You are a financial market analyst.
Explain in simple terms why U.S. stock market volatility often increases during elections.
"""

inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

print("Running inference...")
with torch.no_grad():
    output = model.generate(
        **inputs,
        max_new_tokens=120,
        do_sample=True,
        temperature=0.7,
        top_p=0.9,
    )

print("\n=== MODEL OUTPUT ===")
print(tokenizer.decode(output[0], skip_special_tokens=True))