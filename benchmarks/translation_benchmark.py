#!/usr/bin/env python3
import argparse
import csv
import json
import time
from pathlib import Path

from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler

MODELS = {
    "qwen": {
        "id": "Qwen/Qwen3-4B-MLX-4bit",
        "kind": "context_llm",
    },
    "gemma": {
        "id": "mlx-community/gemma-3-text-4b-it-4bit",
        "kind": "context_llm",
    },
    "translategemma": {
        "id": "mlx-community/translategemma-4b-it-4bit",
        "kind": "translate_gemma",
    },
}

SYSTEM = """You translate English live-stream captions into concise, natural Japanese subtitles.
Use the recent dialogue only as context. Translate CURRENT only.
Preserve product names and follow the glossary exactly.
Do not explain. Output Japanese translation only.
Prefer natural spoken Japanese over literal wording.
Keep the subtitle concise without dropping meaning."""

def build_context_prompt(tokenizer, case):
    context = "\n".join(case.get("context", [])[-3:]) or "(none)"
    glossary = "\n".join(f"- {x}" for x in case.get("glossary", [])) or "(none)"
    user = f"""RECENT CONTEXT:
{context}

GLOSSARY:
{glossary}

CURRENT:
{case["current"]}"""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )

def build_translate_gemma_prompt(tokenizer, case):
    # TranslateGemma's official template expects exactly one translation item.
    messages = [{
        "role": "user",
        "content": [{
            "type": "text",
            "source_lang_code": "en",
            "target_lang_code": "ja",
            "text": case["current"],
        }],
    }]
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

def run_one(model, tokenizer, model_kind, case, max_tokens):
    prompt = (
        build_translate_gemma_prompt(tokenizer, case)
        if model_kind == "translate_gemma"
        else build_context_prompt(tokenizer, case)
    )

    started = time.perf_counter()
    first = None
    chunks = []
    token_count = 0

    for response in stream_generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=max_tokens,
        sampler=make_sampler(temp=0.0),
    ):
        text = getattr(response, "text", "")
        if text and first is None:
            first = time.perf_counter()
        if text:
            chunks.append(text)
            if "<end_of_turn>" in text:
                break
        token_count += 1

    ended = time.perf_counter()
    output = "".join(chunks).split("<end_of_turn>", 1)[0].strip()
    ttft_ms = ((first or ended) - started) * 1000
    total_ms = (ended - started) * 1000
    gen_seconds = max((ended - (first or ended)), 1e-9)

    return {
        "output": output,
        "ttft_ms": round(ttft_ms, 1),
        "total_ms": round(total_ms, 1),
        "output_tokens": token_count,
        "decode_tok_s": round(token_count / gen_seconds, 2) if token_count else 0.0,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="qwen,gemma,translategemma")
    parser.add_argument("--cases", default=str(Path(__file__).with_name("translation_cases.json")))
    parser.add_argument("--output", default="translation-benchmark-results.json")
    parser.add_argument("--csv", default="translation-benchmark-results.csv")
    parser.add_argument("--max-tokens", type=int, default=96)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = json.loads(Path(args.cases).read_text())["cases"]
    if args.limit:
        cases = cases[:args.limit]

    selected = [x.strip() for x in args.models.split(",") if x.strip()]
    results = []

    for alias in selected:
        spec = MODELS[alias]
        print(f"\n=== Loading {alias}: {spec['id']} ===", flush=True)
        load_started = time.perf_counter()
        model, tokenizer = load(spec["id"])
        load_s = time.perf_counter() - load_started
        print(f"Loaded in {load_s:.2f}s", flush=True)

        # Warmup so model-load/compile cost is not mixed into caption latency.
        warm_case = cases[0]
        _ = run_one(model, tokenizer, spec["kind"], warm_case, 24)

        for case in cases:
            print(f"[{alias}] {case['id']} ...", flush=True)
            row = {
                "model": alias,
                "model_id": spec["id"],
                "case_id": case["id"],
                "source": case["current"],
                "context": case.get("context", []),
                "glossary": case.get("glossary", []),
            }
            row.update(run_one(model, tokenizer, spec["kind"], case, args.max_tokens))
            results.append(row)
            print(
                f"  TTFT={row['ttft_ms']}ms total={row['total_ms']}ms "
                f"decode={row['decode_tok_s']} tok/s\n  {row['output']}",
                flush=True,
            )

        del model
        del tokenizer

    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2))

    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "model", "model_id", "case_id", "ttft_ms", "total_ms",
                "output_tokens", "decode_tok_s", "source", "output"
            ],
        )
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})

    print(f"\nWrote {args.output} and {args.csv}")

if __name__ == "__main__":
    main()
