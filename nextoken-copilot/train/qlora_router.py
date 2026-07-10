"""QLoRA fine-tune of the NexToken Copilot router (Kaggle 2xT4).

Distils the three router decisions (plan / route / tool-select) into a small
model. Reads the chat-format dataset produced by
``scripts/build_ft_dataset.py`` and trains 4-bit LoRA adapters.

Run on Kaggle (GPU T4 x2) or any CUDA GPU >= 12 GB:

    pip install -r requirements-kaggle.txt
    python qlora_router.py --data ft_router.jsonl --base Qwen/Qwen2.5-1.5B-Instruct

Output: ./router-lora (LoRA adapter). See README.md for serving + wiring.
"""
from __future__ import annotations

import argparse

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="ft_router.jsonl")
    p.add_argument("--base", default="Qwen/Qwen2.5-1.5B-Instruct")
    p.add_argument("--out", default="router-lora")
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--max-seq", type=int, default=1024)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Render each {"messages":[...]} example with the model's chat template.
    ds = load_dataset("json", data_files=args.data, split="train")

    def to_text(example):
        return {"text": tokenizer.apply_chat_template(example["messages"], tokenize=False)}

    ds = ds.map(to_text, remove_columns=ds.column_names)

    # 4-bit NF4 quantization; float16 compute (T4 has no bf16).
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.base, quantization_config=bnb, device_map="auto", torch_dtype=torch.float16
    )
    model.config.use_cache = False

    lora = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    cfg = SFTConfig(
        output_dir=args.out,
        dataset_text_field="text",
        max_seq_length=args.max_seq,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=2,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=5,
        save_strategy="epoch",
        fp16=True,
        bf16=False,
        packing=False,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        args=cfg,
        train_dataset=ds,
        peft_config=lora,
        tokenizer=tokenizer,
    )
    trainer.train()
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"\nSaved LoRA adapter -> {args.out}")

    # Sanity generation on the three router tasks.
    checks = [
        ("You are an orchestrator. Break the user's question into 1-3 short, independent sub-tasks, one per line.",
         "what is my balance and list my api keys"),
        ("You are a supervisor. Choose exactly one worker for the sub-task. Reply with only the worker name.",
         "options=usage,billing,catalog,finance :: task=what is our gross margin by model"),
    ]
    model.config.use_cache = True
    for system, user in checks:
        prompt = tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tokenize=False, add_generation_prompt=True,
        )
        ids = tokenizer(prompt, return_tensors="pt").to(model.device)
        out = model.generate(**ids, max_new_tokens=40, do_sample=False)
        print("\nUSER:", user, "\n->", tokenizer.decode(out[0][ids.input_ids.shape[1]:], skip_special_tokens=True))


if __name__ == "__main__":
    main()
