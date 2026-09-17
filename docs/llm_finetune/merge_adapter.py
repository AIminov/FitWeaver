"""Merge LoRA adapter with base model to create a standalone model."""

import argparse
import logging
from pathlib import Path

from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main(
    checkpoint_path: str = "Build_artifacts/functiongemma-270m-finetuned/checkpoint-800",
    base_model: str = "google/functiongemma-270m-it",
    output_path: str = "Build_artifacts/functiongemma-270m-finetuned-merged",
):
    """Merge fine-tuned checkpoint into standalone model."""

    checkpoint_path = Path(checkpoint_path)
    output_path = Path(output_path)

    logger.info(f"Loading base model {base_model}...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=2048,
        dtype=None,
        load_in_4bit=False,
    )

    logger.info(f"Loading LoRA from checkpoint {checkpoint_path}...")
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, str(checkpoint_path))

    # Merge LoRA weights into base model
    logger.info("Merging LoRA weights...")
    model = model.merge_and_unload()

    # Save merged model
    output_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Saving merged model to {output_path}...")
    model.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)

    logger.info("✅ Merged model saved!")
    logger.info(f"Next: Load in LM Studio from {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge LoRA adapter with base model")
    parser.add_argument("--checkpoint", default="Build_artifacts/functiongemma-270m-finetuned/checkpoint-800")
    parser.add_argument("--base", default="google/functiongemma-270m-it")
    parser.add_argument("--output", default="Build_artifacts/functiongemma-270m-finetuned-merged")
    args = parser.parse_args()

    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    checkpoint = PROJECT_ROOT / args.checkpoint
    output = PROJECT_ROOT / args.output

    main(str(checkpoint), args.base, str(output))
