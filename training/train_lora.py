"""Run private Gemma 4 E2B QLoRA on an external CUDA GPU.

The reserved holdout file is intentionally never opened by this program.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("train_jsonl", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--model", default="google/gemma-4-E2B")
    parser.add_argument("--processor", default="google/gemma-4-E2B-it")
    parser.add_argument("--epochs", type=int, default=2)
    args = parser.parse_args()
    if args.epochs < 1 or args.epochs > 5:
        raise ValueError("epochs must be between 1 and 5")
    if "holdout" in args.train_jsonl.name.casefold():
        raise ValueError("holdout data cannot be used for fitting")

    import torch
    from datasets import Dataset
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForMultimodalLM, AutoProcessor, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    if not torch.cuda.is_available():
        raise RuntimeError("QLoRA training requires an external CUDA GPU")
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    rows = [json.loads(line) for line in args.train_jsonl.read_text(encoding="utf-8").splitlines()]
    if not rows:
        raise ValueError("training dataset is empty")
    if any(len(row.get("messages", [])) != 2 for row in rows):
        raise ValueError("all examples must have user and assistant messages")
    dataset = Dataset.from_list(rows)
    processor = AutoProcessor.from_pretrained(args.processor)
    tokenizer = processor.tokenizer
    model = AutoModelForMultimodalLM.from_pretrained(
        args.model,
        dtype=dtype,
        device_map="auto",
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=dtype,
            bnb_4bit_quant_storage=dtype,
        ),
    )
    if torch.cuda.get_device_properties(0).total_memory > 16 * 1024**3:
        model = prepare_model_for_kbit_training(model)

    def collate(examples):
        ids = []
        labels = []
        for example in examples:
            full = tokenizer.apply_chat_template(
                example["messages"], tokenize=False, add_generation_prompt=False
            )
            prompt = tokenizer.apply_chat_template(
                example["messages"][:1], tokenize=False, add_generation_prompt=True
            )
            full_ids = tokenizer(full, add_special_tokens=False, truncation=True, max_length=512).input_ids
            prompt_ids = tokenizer(prompt, add_special_tokens=False).input_ids
            if full_ids[:len(prompt_ids)] != prompt_ids or len(full_ids) <= len(prompt_ids):
                raise ValueError("Gemma chat template cannot safely mask this example")
            ids.append(torch.tensor(full_ids, dtype=torch.long))
            labels.append(torch.tensor([-100] * len(prompt_ids) + full_ids[len(prompt_ids):], dtype=torch.long))
        pad = tokenizer.pad_token_id
        if pad is None:
            raise ValueError("Gemma processor has no pad token")
        input_ids = torch.nn.utils.rnn.pad_sequence(ids, batch_first=True, padding_value=pad)
        return {
            "input_ids": input_ids,
            "attention_mask": (input_ids != pad).long(),
            "labels": torch.nn.utils.rnn.pad_sequence(labels, batch_first=True, padding_value=-100),
        }

    options = SFTConfig(
        output_dir=str(args.output_dir),
        max_length=512,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        save_strategy="epoch",
        eval_strategy="no",
        push_to_hub=False,
        report_to=[],
        dataset_kwargs={"skip_prepare_dataset": True},
        remove_unused_columns=False,
        bf16=dtype == torch.bfloat16,
        fp16=dtype == torch.float16,
    )
    trainer = SFTTrainer(
        model=model,
        args=options,
        train_dataset=dataset,
        peft_config=LoraConfig(
            r=16, lora_alpha=16, lora_dropout=0.05, bias="none",
            task_type="CAUSAL_LM", modules_to_save=["lm_head", "embed_tokens"],
            ensure_weight_tying=True,
        ),
        processing_class=processor,
        data_collator=collate,
    )
    trainer.train()
    trainer.save_model(str(args.output_dir))


if __name__ == "__main__":
    main()
