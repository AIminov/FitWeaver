"""Simple fine-tuning script for FunctionGemma 270M using Unsloth."""

import argparse
import logging
from pathlib import Path

import yaml
from datasets import Dataset
from transformers import TrainingArguments, Trainer, DataCollatorForLanguageModeling
from unsloth import FastLanguageModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_FILE = PROJECT_ROOT / "docs" / "llm_finetune" / "golden_examples_v1.yaml"


def main(
    model_id: str = "unsloth/functiongemma-270m-it",
    output_dir: str = "Build_artifacts/functiongemma-270m-finetuned",
    epochs: int = 3,
    batch_size: int = 2,
):
    """Fine-tune FunctionGemma on golden workout examples."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Load examples
    logger.info(f"Loading {GOLDEN_FILE}...")
    if not GOLDEN_FILE.exists():
        raise FileNotFoundError(f"Golden file not found: {GOLDEN_FILE}")

    with open(GOLDEN_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "groups" not in data:
        raise ValueError(f"Invalid YAML: no 'groups' key or empty file: {GOLDEN_FILE}")

    valid_groups = [g for g in data["groups"] if g.get("status") == "VALID"]
    logger.info(f"Found {len(valid_groups)} VALID groups out of {len(data['groups'])} total")

    # Create training texts (simple: user text → YAML output)
    texts = []
    for group in valid_groups:
        for variant in group.get("variants", []):
            # Simple format: input text followed by expected YAML
            text = f"User: {variant['text']}\n\nAssistant: ```yaml\n"
            text += yaml.dump(group["canonical"], default_flow_style=False, allow_unicode=True)
            text += "```"
            texts.append(text)

    logger.info(f"Prepared {len(texts)} training examples")

    if not texts:
        raise ValueError("No training examples found!")

    # Load model
    logger.info(f"Loading {model_id}...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_id,
        max_seq_length=2048,
        dtype=None,
        load_in_4bit=True,
    )

    # Setup LoRA
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        lora_alpha=16,
        lora_dropout=0,  # 0 for Unsloth fast patching
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    # Prepare dataset
    dataset = Dataset.from_dict({"text": texts})

    def tokenize_fn(examples):
        output = tokenizer(
            examples["text"],
            truncation=True,
            max_length=2048,
            padding="max_length",
        )
        output["labels"] = output["input_ids"].copy()
        return output

    train_dataset = dataset.map(tokenize_fn, batched=True, remove_columns=["text"])
    logger.info(f"Tokenized: {len(train_dataset)} examples")

    # Train
    training_args = TrainingArguments(
        output_dir=str(output_path),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        warmup_steps=5,
        logging_steps=1,
        save_steps=max(1, len(train_dataset) // batch_size // 2),
        save_total_limit=2,
        optim="paged_adamw_8bit",
        seed=42,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )

    logger.info("Starting fine-tuning...")
    trainer.train()

    logger.info("✅ Fine-tuning complete!")
    model.save_pretrained(output_path / "adapter")
    tokenizer.save_pretrained(output_path)
    logger.info(f"Saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default="unsloth/functiongemma-270m-it")
    parser.add_argument("--output-dir", default="Build_artifacts/functiongemma-270m-finetuned")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=2)

    args = parser.parse_args()
    main(args.model_id, args.output_dir, args.epochs, args.batch_size)
