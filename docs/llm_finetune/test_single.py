"""Quick test: generate for one example only."""

from pathlib import Path
import yaml
from unsloth import FastLanguageModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_FILE = PROJECT_ROOT / "docs" / "llm_finetune" / "golden_examples_v1.yaml"
MERGED_MODEL = PROJECT_ROOT / "Build_artifacts" / "functiongemma-270m-finetuned-merged"

print("Loading model...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=str(MERGED_MODEL),
    max_seq_length=2048,
    dtype=None,
    load_in_4bit=False,
)
FastLanguageModel.for_inference(model)

print("Loading golden examples...")
with open(GOLDEN_FILE, encoding="utf-8") as f:
    data = yaml.safe_load(f)

valid_groups = [g for g in data["groups"] if g.get("status") == "VALID"]
group = valid_groups[0]
variant = group["variants"][0]

print(f"\nTesting: {group['group_id']}")
print(f"User text: {variant['text'][:100]}...")

print("\nGenerating (this may take 30-60 sec)...")
inputs = tokenizer(variant["text"], return_tensors="pt").to(model.device)

outputs = model.generate(
    **inputs,
    max_new_tokens=256,
    temperature=0.1,
    do_sample=False,
)

generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(f"\nGenerated ({len(generated_text)} chars):")
print(generated_text[-200:])  # Last 200 chars
