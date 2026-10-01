# Translation benchmark

Live-caption English → Japanese benchmark for the local translation backend.

## Models

| Alias | Model | Purpose |
|---|---|---|
| `gemma3` | `mlx-community/gemma-3-text-4b-it-4bit` | Current baseline |
| `gemma4e4b` | `Siarhei/gemma-4-E4B-4bit` | Gemma 4 small text-generation candidate |
| `gemma4-12b` | `DreamFoundries/gemma-4-12B-it-4bit` | Gemma 4 higher-quality text-generation candidate |
| `qwen` | `Qwen/Qwen3-4B-MLX-4bit` | Context-aware comparison baseline |
| `translategemma` | `mlx-community/translategemma-4b-it-4bit` | Translation-specialized reference |

Gemma 3, Gemma 4 and Qwen receive the last three dialogue turns plus glossary terms. TranslateGemma is evaluated separately with its structured translation prompt and receives only the current utterance.

## Run on Apple Silicon

```bash
./scripts/benchmark-translation.sh
```

Quick smoke test:

```bash
./scripts/benchmark-translation.sh --limit 2
```

Single model:

```bash
./scripts/benchmark-translation.sh --models gemma4e4b

# Higher-quality candidate only
./scripts/benchmark-translation.sh --models gemma4-12b
```

Outputs:

- `translation-benchmark-results.json`
- `translation-benchmark-results.csv`

The first run downloads the selected models. Later runs use the Hugging Face cache.

## Measurements

The harness records:

- **TTFT** — time until the first generated text
- **total_ms** — time until the subtitle translation finishes
- **decode_tok_s** — generated tokens per second
- actual Japanese output for manual quality review

For live subtitles, total latency matters more than raw tokens/sec because output is intentionally short.

## Manual quality rubric

Score each output from 0–2 on these dimensions:

1. **Meaning** — preserves the source meaning and negation
2. **Natural Japanese** — sounds like a Japanese subtitle rather than a literal translation
3. **Context** — resolves pronouns/ambiguous words from preceding turns
4. **Terminology** — preserves product names and follows glossary terms
5. **Compactness** — concise enough to read live

Maximum: 10 points per case.

Useful cases in `translation_cases.json` deliberately test:

- “shipping” as software release vs physical shipment
- pronouns across turns
- FluidAudio / Parakeet / Sortformer terminology
- idioms and casual speech
- negation
- numbers and latency
- interruptions
- subtitle compactness

## Selection rule for the extension

A practical winner should satisfy both:

- median total translation latency low enough for a rolling ~3 second subtitle chunk
- consistently high manual scores on context, terminology and naturalness

If TranslateGemma is clearly fastest but loses context-dependent cases, it can still be kept as a `fast` mode while the best context LLM becomes `smart` mode.
