#!/usr/bin/env python3
import argparse
import json
import re
import time
import unicodedata
from pathlib import Path


def normalize_text(text):
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = re.sub(r"[^\w\s\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(
                cur[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + (x != y),
            ))
        prev = cur
    return prev[-1]


def canonicalize_asr_display(text):
    value = normalize_text(text)
    replacements = {
        "gemma four": "gemma4",
        "nine sixty": "960",
        "six forty": "640",
        "nine hundred sixty": "960",
        "six hundred forty": "640",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    return value


def error_rates(reference, hypothesis):
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    ref_words, hyp_words = ref.split(), hyp.split()
    ref_chars = list(ref.replace(" ", ""))
    hyp_chars = list(hyp.replace(" ", ""))

    canon_ref = canonicalize_asr_display(reference)
    canon_hyp = canonicalize_asr_display(hypothesis)
    canon_ref_words, canon_hyp_words = canon_ref.split(), canon_hyp.split()

    return {
        "wer": round(levenshtein(ref_words, hyp_words) / max(1, len(ref_words)), 4),
        "cer": round(levenshtein(ref_chars, hyp_chars) / max(1, len(ref_chars)), 4),
        "display_normalized_wer": round(
            levenshtein(canon_ref_words, canon_hyp_words) / max(1, len(canon_ref_words)),
            4,
        ),
    }


def run_qwen(audio, model_id, language):
    from mlx_qwen3_asr import Session
    load_start = time.perf_counter()
    session = Session(model=model_id)
    load_s = time.perf_counter() - load_start

    started = time.perf_counter()
    result = session.transcribe(audio, language=language or None)
    elapsed = time.perf_counter() - started
    return {
        "model": model_id,
        "engine": "qwen3-asr",
        "load_s": round(load_s, 3),
        "transcribe_s": round(elapsed, 3),
        "text": str(result.text or "").strip(),
        "detected_language": str(result.language or ""),
    }


def run_gemma(audio, model_id):
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template

    load_start = time.perf_counter()
    model, processor = load(model_id)
    load_s = time.perf_counter() - load_start

    prompt = apply_chat_template(
        processor,
        model.config,
        "Transcribe this audio exactly. Output only the transcription with natural punctuation. Do not translate or explain.",
        num_audios=1,
    )

    started = time.perf_counter()
    result = generate(
        model=model,
        processor=processor,
        prompt=prompt,
        audio=[audio],
        max_tokens=512,
        temperature=0.0,
    )
    elapsed = time.perf_counter() - started
    text = getattr(result, "text", result)
    return {
        "model": model_id,
        "engine": "gemma4-audio",
        "load_s": round(load_s, 3),
        "transcribe_s": round(elapsed, 3),
        "text": str(text or "").strip(),
        "detected_language": "",
    }


def main():
    parser = argparse.ArgumentParser(description="Compare local ASR models on one audio file.")
    parser.add_argument("audio")
    parser.add_argument("--reference", default="")
    parser.add_argument("--reference-file", default="")
    parser.add_argument("--language", default="")
    parser.add_argument(
        "--models",
        default="gemma4e4b,qwen06,qwen17",
        help="comma-separated: gemma4e4b,qwen06,qwen17",
    )
    parser.add_argument("--output", default="asr-benchmark-results.json")
    args = parser.parse_args()

    audio = str(Path(args.audio).expanduser().resolve())
    if not Path(audio).exists():
        raise SystemExit(f"Audio file not found: {audio}")

    reference = args.reference
    if args.reference_file:
        reference = Path(args.reference_file).read_text(encoding="utf-8").strip()

    specs = {
        "gemma4e4b": ("gemma", "mlx-community/gemma-4-e4b-it-4bit"),
        "qwen06": ("qwen", "moona3k/mlx-qwen3-asr-0.6b-4bit"),
        "qwen17": ("qwen", "moona3k/mlx-qwen3-asr-1.7b-4bit"),
    }

    results = []
    for alias in [x.strip() for x in args.models.split(",") if x.strip()]:
        if alias not in specs:
            raise SystemExit(f"Unknown model alias: {alias}")
        kind, model_id = specs[alias]
        print(f"\n=== {alias}: {model_id} ===", flush=True)
        row = run_gemma(audio, model_id) if kind == "gemma" else run_qwen(audio, model_id, args.language)
        row["alias"] = alias
        row["audio"] = audio
        if reference:
            row["reference"] = reference
            row.update(error_rates(reference, row["text"]))
        results.append(row)
        print(f"load={row['load_s']}s transcribe={row['transcribe_s']}s", flush=True)
        if reference:
            print(
                f"WER={row['wer']} CER={row['cer']} "
                f"display-normalized-WER={row['display_normalized_wer']}",
                flush=True,
            )
        print(row["text"], flush=True)

    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
