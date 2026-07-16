"""QLoRA fine-tune of the NexToken Copilot router (Kaggle 2xT4).

Distils the three router decisions (plan / route / tool-select) into a small
model. Reads the chat-format dataset produced by
``scripts/build_ft_dataset.py`` and trains 4-bit LoRA adapters.

Plain ``transformers.Trainer`` + ``peft`` on purpose — no TRL. TRL's SFT
wrapper broke twice on the current Kaggle image (2024-pin import crash, then
its chunked-CE forward patch vs accelerate's ``functools.partial`` wrapping
on quantized ``device_map`` models); for full-text SFT on a small dataset it
buys nothing over the stable core APIs.

Run on Kaggle (GPU T4) or any CUDA GPU >= 12 GB:

    pip install -r requirements-kaggle.txt
    python qlora_router.py --data ft_router.jsonl --base Qwen/Qwen2.5-1.5B-Instruct

Output: ./router-lora (LoRA adapter). See README.md for serving + wiring.
"""
from __future__ import annotations

import argparse

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
)


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

    # Render each {"messages":[...]} example with the model's chat template,
    # then tokenize (full-text loss — simple and fine at this dataset size).
    ds = load_dataset("json", data_files=args.data, split="train")
    ds = ds.map(lambda ex: {"text": tokenizer.apply_chat_template(ex["messages"], tokenize=False)},
                remove_columns=ds.column_names)
    ds = ds.map(lambda ex: tokenizer(ex["text"], truncation=True, max_length=args.max_seq),
                remove_columns=["text"])

    # 4-bit NF4 quantization; float16 compute (T4 has no bf16). Single device:
    # a 1.5B fits a T4 several times over, and single-GPU load avoids
    # accelerate's dispatch wrappers entirely.
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.base, quantization_config=bnb, device_map={"": 0}
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    ))
    model.print_trainable_parameters()

    train_args = TrainingArguments(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=2,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=5,
        save_strategy="no",
        fp16=True,
        report_to="none",
    )
    trainer = Trainer(
        model=model,
        args=train_args,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )
    trainer.train()
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"\nSaved LoRA adapter -> {args.out}")

    # Sanity generation on the router tasks.
    checks = [
        ("You are an orchestrator. Break the user's question into 1-3 short, independent sub-tasks, one per line.",
         "what is my balance and list my api keys"),
        ("You are a supervisor. Choose exactly one worker for the sub-task. Reply with only the worker name.",
         "options=usage,billing,catalog,finance,help :: task=what is our gross margin by model"),
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
