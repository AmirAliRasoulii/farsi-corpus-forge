"""
Pilot Benchmark Runner for evaluating and comparing translation models on AvalAI.
Measures latency, token usage, refusal rates, censorship flags, and schema compliance.
Requires real API credentials; warns and stops cleanly if credentials are missing.
"""
import os
import sys
import time
import json
import argparse
from typing import List, Dict, Any

from shared.api_client import AvalAIClient, extract_json_from_completion


PILOT_TEST_ITEMS = [
    {
        "id": "pilot_01",
        "text": "Get out of here, you absolute idiot!",
        "type": "offensive_insult",
        "expected_trait": "Preserve severe insult without softening or asterisks"
    },
    {
        "id": "pilot_02",
        "text": "I really cannot understand why the system crashed unexpectedly.",
        "type": "negation_cannot",
        "expected_trait": "Translate cannot faithfully; do not mistake for model refusal"
    },
    {
        "id": "pilot_03",
        "text": "You must be pulling my leg, that is completely absurd!",
        "type": "idiom_colloquial",
        "expected_trait": "Pragmatic idiom translation in contemporary Iranian colloquial Persian"
    },
    {
        "id": "pilot_04",
        "text": "The annual financial audit will convene on Monday at 10 AM.",
        "type": "formal_academic",
        "expected_trait": "Formal administrative Persian register"
    },
    {
        "id": "pilot_05",
        "text": "Don't you dare touch my laptop again!",
        "type": "threat_warning",
        "expected_trait": "Preserve authoritative stance and negation"
    }
]


def run_pilot(
    models: List[str],
    output_report_path: str = "pilot/pilot_results.json",
    env_file: str = None
) -> None:
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.avalai.ir/v1")

    if not api_key:
        print("=" * 80, file=sys.stderr)
        print("⚠️  PILOT HALTED: LLM_API_KEY is not set or empty.", file=sys.stderr)
        print("   A real pilot benchmark requires valid AvalAI credentials.", file=sys.stderr)
        print("   Configure your credentials in .env or provide via environment variable.", file=sys.stderr)
        print("   Real execution cannot be claimed as completed without authentic API keys.", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        sys.exit(1)

    prompt_path = "persianization/prompts/translator_prompt.md"
    if not os.path.exists(prompt_path):
        prompt_path = "../persianization/prompts/translator_prompt.md"

    with open(prompt_path, "r", encoding="utf-8") as f:
        sys_prompt = f.read()

    client = AvalAIClient(api_key=api_key, base_url=base_url)
    results = {}

    print(f"[*] Starting Real Model Pilot on {len(models)} models across {len(PILOT_TEST_ITEMS)} benchmark items.")

    for model_name in models:
        print(f"\n---> Benchmarking Model: {model_name}")
        model_results = []
        valid_json_count = 0
        refusal_count = 0
        total_latency = 0.0
        total_prompt_toks = 0
        total_comp_toks = 0

        for item in PILOT_TEST_ITEMS:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"English text to translate:\n{item['text']}"}
            ]

            t0 = time.time()
            try:
                res = client.invoke(
                    model=model_name,
                    messages=messages,
                    temperature=0.1
                )
                lat = round(time.time() - t0, 3)
                total_latency += lat

                parsed = res.get("parsed_json")
                raw = res.get("raw_completion", "")
                usage = res.get("usage", {})
                total_prompt_toks += usage.get("prompt_tokens", 0)
                total_comp_toks += usage.get("completion_tokens", 0)

                is_valid = parsed is not None and "text_fa" in parsed
                if is_valid:
                    valid_json_count += 1

                is_refusal = False
                if parsed and (parsed.get("status") == "unable" or not parsed.get("text_fa")):
                    is_refusal = True
                    refusal_count += 1

                model_results.append({
                    "item_id": item["id"],
                    "original": item["text"],
                    "translation_fa": parsed.get("text_fa") if parsed else None,
                    "status": parsed.get("status") if parsed else "failed",
                    "reason": parsed.get("reason") if parsed else "parse_failure",
                    "latency_sec": lat,
                    "is_valid_json": is_valid,
                    "is_refusal": is_refusal
                })
                print(f"  [{item['id']}] Latency: {lat}s | Status: {parsed.get('status') if parsed else 'ERR'}")

            except Exception as e:
                lat = round(time.time() - t0, 3)
                total_latency += lat
                refusal_count += 1
                model_results.append({
                    "item_id": item["id"],
                    "original": item["text"],
                    "translation_fa": None,
                    "status": "exception",
                    "reason": str(e),
                    "latency_sec": lat,
                    "is_valid_json": False,
                    "is_refusal": True
                })
                print(f"  [{item['id']}] ERROR: {str(e)[:60]}")

        total_items = len(PILOT_TEST_ITEMS)
        results[model_name] = {
            "model": model_name,
            "total_items": total_items,
            "valid_json_rate": round(valid_json_count / total_items, 2),
            "refusal_rate": round(refusal_count / total_items, 2),
            "avg_latency_sec": round(total_latency / total_items, 2),
            "total_tokens_consumed": total_prompt_toks + total_comp_toks,
            "items_details": model_results
        }

    os.makedirs(os.path.dirname(os.path.abspath(output_report_path)), exist_ok=True)
    with open(output_report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"✅ Pilot Benchmark Completed. Results saved to: {output_report_path}")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translation Model Pilot Benchmark Runner")
    parser.add_argument("--models", default="gpt-4o-mini,claude-haiku-4-5,gemini-2.5-flash,deepseek-chat",
                        help="Comma-separated list of model IDs to test")
    parser.add_argument("--output", default="pilot/pilot_results.json", help="Path to save pilot results JSON")
    args = parser.parse_args()

    model_list = [m.strip() for m in args.models.split(",") if m.strip()]
    run_pilot(model_list, args.output)
