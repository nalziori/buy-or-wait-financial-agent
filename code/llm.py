"""Gemini REST client (stdlib only) with an on-disk response cache and token accounting."""
import base64
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")  # matches the model the shipped cache/output.csv were built with
# USD per 1M tokens, official Gemini API standard (non-batch) pricing as of 2026-09-13.
# Source: https://ai.google.dev/gemini-api/docs/pricing (confirmed via independent web search).
# gemini-3.6-flash is on a promotional rate through 2026-12-31, reverting to the 3.5-flash rate in 2027.
OFFICIAL_PRICE_PER_M = {
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
}
CACHE_PATH = Path(__file__).resolve().parent / "cache" / "llm_cache.json"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
RETRYABLE = {429, 500, 502, 503, 504}
ATTEMPTS = 5


class LLM:
    def __init__(self, model=MODEL):
        self.model = model
        self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
        self.calls = []
        self.lock = threading.Lock()

    def json_call(self, purpose, parts, schema, thinking=None):
        """parts: list of str (text) or Path (PNG image), sent in order as one user turn."""
        thinking = thinking or {"thinkingLevel": "low"}
        digest = hashlib.sha256(json.dumps([self.model, schema, thinking]).encode())
        payload = []
        for part in parts:
            if isinstance(part, Path):
                data = part.read_bytes()
                digest.update(data)
                payload.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(data).decode()}})
            else:
                digest.update(part.encode())
                payload.append({"text": part})
        key = digest.hexdigest()
        with self.lock:
            entry = self.cache.get(key)
        cached = entry is not None
        if not cached:
            entry = self._request(payload, schema, thinking)
            with self.lock:
                self.cache[key] = entry
                self._save()
        with self.lock:
            self.calls.append({"purpose": purpose, "cached": cached, **entry["usage"]})
        return entry["output"]

    def _request(self, payload, schema, thinking):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set and this response is not in the cache")
        body = {
            "contents": [{"role": "user", "parts": payload}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "thinkingConfig": thinking,
            },
        }
        request = urllib.request.Request(
            URL.format(self.model),
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        )
        for attempt in range(ATTEMPTS):
            wait = 3 * 2**attempt
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as err:
                detail = err.read().decode(errors="replace")
                if err.code not in RETRYABLE or attempt == ATTEMPTS - 1:
                    raise RuntimeError(f"Gemini {self.model} HTTP {err.code}: {detail[:500]}") from err
                hint = re.search(r"retry in ([\d.]+)s", detail)
                wait = max(wait, float(hint.group(1)) + 2) if hint else wait
            except (urllib.error.URLError, TimeoutError):
                if attempt == ATTEMPTS - 1:
                    raise
            time.sleep(wait)
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        meta = data.get("usageMetadata", {})
        return {
            "output": json.loads(text),
            "usage": {
                "input_tokens": meta.get("promptTokenCount", 0),
                "output_tokens": meta.get("candidatesTokenCount", 0) + meta.get("thoughtsTokenCount", 0),
            },
        }

    def _save(self):
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")
        tmp.replace(CACHE_PATH)

    def write_usage_report(self, path, n_requests):
        if self.model not in OFFICIAL_PRICE_PER_M:
            raise RuntimeError(
                f"No verified official price for model '{self.model}' in OFFICIAL_PRICE_PER_M. "
                "Add a confirmed rate (with source) before writing the usage report -- do not guess."
            )
        price = OFFICIAL_PRICE_PER_M[self.model]

        def cost(inp, out):
            return inp / 1e6 * price["input"] + out / 1e6 * price["output"]

        by_purpose = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        for c in self.calls:
            row = by_purpose[c["purpose"]]
            row["calls"] += 1
            row["input_tokens"] += c["input_tokens"]
            row["output_tokens"] += c["output_tokens"]
        calls = len(self.calls)
        inp = sum(c["input_tokens"] for c in self.calls)
        out = sum(c["output_tokens"] for c in self.calls)
        total = cost(inp, out)
        per_request = n_requests or 1
        lines = [
            "# Token Usage and Cost Report",
            "",
            "Final full-dataset run that produced `output.csv`.",
            "",
            "- Provider: Google (Gemini API)",
            f"- Model: `{self.model}` (only model used)",
            f"- Pricing: USD {price['input']:.2f} / 1M input tokens, USD {price['output']:.2f} / 1M output tokens -- official Gemini API standard rate, https://ai.google.dev/gemini-api/docs/pricing (checked 2026-09-13). Output includes thinking tokens.",
            f"- Requests in `dataset/requests.csv`: {n_requests}",
            "- Deterministic Python makes every affordability decision. The model only reads images (blank amounts) and messages (typed facts), in batches.",
            "- Responses are cached on disk (`code/cache/llm_cache.json`). Token counts are the tokens originally spent to produce every response this run used, whether served live or from cache.",
            "",
            "## Per model",
            "",
            "| Model | Calls | Served from cache | Input tokens | Output tokens | Total tokens | Est. cost (USD) |",
            "|---|---:|---:|---:|---:|---:|---:|",
            f"| {self.model} | {calls} | {sum(c['cached'] for c in self.calls)} | {inp:,} | {out:,} | {inp + out:,} | {total:.4f} |",
            "",
            "## Per purpose",
            "",
            "| Purpose | Calls | Input tokens | Output tokens | Est. cost (USD) |",
            "|---|---:|---:|---:|---:|",
        ]
        for purpose, row in sorted(by_purpose.items()):
            lines.append(
                f"| {purpose} | {row['calls']} | {row['input_tokens']:,} | {row['output_tokens']:,} | {cost(row['input_tokens'], row['output_tokens']):.4f} |"
            )
        lines += [
            "",
            "## Overall",
            "",
            f"- Model calls: {calls}",
            f"- Input tokens: {inp:,}",
            f"- Output tokens: {out:,}",
            f"- Total tokens: {inp + out:,}",
            f"- Average tokens per request: {(inp + out) / per_request:,.1f}",
            f"- Estimated total cost: USD {total:.4f}",
            f"- Estimated cost per request: USD {total / per_request:.6f}",
            "",
        ]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("\n".join(lines), encoding="utf-8")
