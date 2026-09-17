"""Test fine-tuned model via Unsloth (optimized for GPU)."""

import json
import logging
from pathlib import Path

import yaml
from unsloth import FastLanguageModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_FILE = PROJECT_ROOT / "docs" / "llm_finetune" / "golden_examples_v1.yaml"
MERGED_MODEL = PROJECT_ROOT / "Build_artifacts" / "functiongemma-270m-finetuned-merged"
OUTPUT_FILE = PROJECT_ROOT / "Build_artifacts" / "llm_finetune_baseline.finetuned-100epochs.json"


def semantic_match(generated_text: str, expected_text: str, tolerance: float = 0.85) -> tuple[bool, float]:
    """Check if generated YAML matches expected structure."""
    gen_lines = {l.strip() for l in generated_text.split('\n') if l.strip() and not l.strip().startswith('#')}
    exp_lines = {l.strip() for l in expected_text.split('\n') if l.strip() and not l.strip().startswith('#')}

    if not gen_lines or not exp_lines:
        return False, 0.0

    matches = len(gen_lines & exp_lines)
    max_possible = max(len(gen_lines), len(exp_lines))
    score = matches / max_possible if max_possible > 0 else 0.0
    return score >= tolerance, score


def main():
    """Test fine-tuned model via Unsloth."""

    logger.info(f"Loading fine-tuned model via Unsloth from {MERGED_MODEL}...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(MERGED_MODEL),
        max_seq_length=2048,
        dtype=None,
        load_in_4bit=False,
    )

    # Prepare for inference
    FastLanguageModel.for_inference(model)

    with open(GOLDEN_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    valid_groups = [g for g in data["groups"] if g.get("status") == "VALID"]
    logger.info(f"Testing {len(valid_groups)} VALID groups\n")

    results = {
        "model": "functiongemma-270m-it (fine-tuned 100 epochs, Unsloth inference)",
        "total_groups": len(valid_groups),
        "groups": {},
        "summary": {}
    }

    schema_valid = 0
    exact_match = 0

    from tqdm import tqdm
    for group_idx, group in tqdm(enumerate(valid_groups, 1), total=len(valid_groups)):
        group_id = group["group_id"]
        variants = group.get("variants", [])

        if not variants:
            continue

        variant = variants[0]
        user_text = variant["text"]
        expected_yaml = yaml.dump(group["canonical"], default_flow_style=False, allow_unicode=True)

        try:
            inputs = tokenizer(user_text, return_tensors="pt").to(model.device)

            outputs = model.generate(
                **inputs,
                max_new_tokens=1024,
                temperature=0.1,
                do_sample=False,
            )
            generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Remove user text from output
            if user_text in generated_text:
                generated_text = generated_text.split(user_text)[-1].strip()

            # Remove code fence if present
            if "```yaml" in generated_text:
                generated_text = generated_text.split("```yaml")[1].split("```")[0].strip()
            elif "```" in generated_text:
                generated_text = generated_text.split("```")[1].split("```")[0].strip()

            is_match, score = semantic_match(generated_text, expected_yaml)
            if is_match:
                exact_match += 1
                status = "✓ EXACT"
            else:
                status = f"✗ partial ({score:.0%})"

            # Try to parse as YAML
            try:
                yaml.safe_load(generated_text)
                schema_valid += 1
                status += " [valid]"
            except:
                status += " [invalid]"

            logger.info(f"  [{group_idx:2d}] {group_id}: {status}")
            results["groups"][group_id] = {
                "exact_match": is_match,
                "semantic_score": score,
            }

        except Exception as e:
            logger.error(f"  [{group_idx:2d}] {group_id}: ERROR - {e}")
            results["groups"][group_id] = {"error": str(e)}

    results["summary"] = {
        "schema_valid_count": schema_valid,
        "schema_valid_pct": f"{100*schema_valid/len(valid_groups):.1f}%",
        "exact_match_count": exact_match,
        "exact_match_pct": f"{100*exact_match/len(valid_groups):.1f}%",
    }

    logger.info("\n" + "="*60)
    logger.info(f"Schema valid: {schema_valid}/{len(valid_groups)} ({100*schema_valid/len(valid_groups):.1f}%)")
    logger.info(f"Exact match:  {exact_match}/{len(valid_groups)} ({100*exact_match/len(valid_groups):.1f}%)")
    logger.info("="*60)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
