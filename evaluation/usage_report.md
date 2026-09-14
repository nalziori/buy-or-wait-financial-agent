# Token Usage and Cost Report

Final full-dataset run that produced `output.csv`.

- Provider: Google (Gemini API)
- Model: `gemini-3.5-flash` (only model used)
- Pricing: USD 1.50 / 1M input tokens, USD 9.00 / 1M output tokens -- official Gemini API standard rate, https://ai.google.dev/gemini-api/docs/pricing (checked 2026-09-13). Output includes thinking tokens.
- Requests in `dataset/requests.csv`: 250
- Deterministic Python makes every affordability decision. The model only reads images (blank amounts) and messages (typed facts), in batches.
- Responses are cached on disk (`code/cache/llm_cache.json`). Token counts are the tokens originally spent to produce every response this run used, whether served live or from cache.

## Per model

| Model | Calls | Served from cache | Input tokens | Output tokens | Total tokens | Est. cost (USD) |
|---|---:|---:|---:|---:|---:|---:|
| gemini-3.5-flash | 11 | 11 | 42,602 | 22,615 | 65,217 | 0.2674 |

## Per purpose

| Purpose | Calls | Input tokens | Output tokens | Est. cost (USD) |
|---|---:|---:|---:|---:|
| image_amounts | 2 | 18,539 | 847 | 0.0354 |
| message_facts | 9 | 24,063 | 21,768 | 0.2320 |

## Overall

- Model calls: 11
- Input tokens: 42,602
- Output tokens: 22,615
- Total tokens: 65,217
- Average tokens per request: 260.9
- Estimated total cost: USD 0.2674
- Estimated cost per request: USD 0.001070
