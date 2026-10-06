"""
Offline End-to-End Mock Demonstration.
Demonstrates Project A (Persianization) and Project B (White Generation) workflows
using simulated offline mock LLM responses. Clearly marked as OFFLINE MOCK DEMO.
"""
import os
import sys
import json
import shutil

from shared.api_client import AvalAIClient
from persianization.cli import run_pipeline
from white_generation.cli import run_white_pipeline
from mock_demo.mock_llm import mock_llm_handler


def run_full_offline_demo():
    print("=" * 80)
    print("🚀 OFFLINE MOCK DEMONSTRATION: TRANSLATION & WHITE GENERATION")
    print("⚠️  NOTICE: This demonstration uses simulated offline responses (mock_llm_handler).")
    print("    It does not consume API credits or connect to the internet.")
    print("=" * 80)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    input_csv = os.path.join(base_dir, "examples", "sample_persianization_input.csv")
    out_dir_a = os.path.join(base_dir, "outputs", "demo_persianization")
    out_dir_b = os.path.join(base_dir, "outputs", "demo_white_generation")

    # Clean existing demo directories if any
    for d in (out_dir_a, out_dir_b):
        if os.path.exists(d):
            shutil.rmtree(d)

    mock_client = AvalAIClient(
        api_key="mock_key_for_testing",
        base_url="https://mock.avalai.ir/v1",
        mock_handler=mock_llm_handler
    )

    # =========================================================================
    # STEP 1: EXECUTE PROJECT A (PERSIANIZATION)
    # =========================================================================
    print("\n[PHASE 1] Executing Project A (Persianization)...")
    res_a = run_pipeline(
        input_file=input_csv,
        output_dir=out_dir_a,
        workers=1,
        mock_client=mock_client
    )

    print(f"\n[✓] Project A completed: {res_a['processed_count']} records processed.")
    print(f"    Exported files in: {out_dir_a}")
    for fname, path in res_a["exported_files"].items():
        size = os.path.getsize(path) if os.path.exists(path) else 0
        print(f"      - {fname}: {os.path.basename(path)} ({size} bytes)")

    # Read summary A
    summary_a_path = res_a["exported_files"]["summary_json"]
    with open(summary_a_path, "r", encoding="utf-8") as f:
        summary_a = json.load(f)
    print(f"\n    Summary A:")
    print(f"      Native Persian (Direct Entry, no model called): {summary_a['native_fa_count']}")
    print(f"      Accepted Translations (English -> Persian):    {summary_a['accepted_translations_count']}")
    print(f"      Total Accepted Persian:                        {summary_a['total_accepted_persian_count']}")
    print(f"      Review Queue (Fingilish / Audit):              {summary_a['review_queue_count']}")

    # =========================================================================
    # STEP 2: EXECUTE PROJECT B (WHITE GENERATION)
    # Consumes accepted Persian from Project A as seeds!
    # =========================================================================
    print("\n" + "=" * 80)
    print("[PHASE 2] Executing Project B (Independent White Generation)...")
    seeds_input = res_a["exported_files"]["accepted_persian_jsonl"]
    print(f"    Consuming accepted Persian records from Project A: {seeds_input}")

    res_b = run_white_pipeline(
        input_file=seeds_input,
        output_dir=out_dir_b,
        limit=3,  # Take first 3 seeds for demonstration
        recipes_filter=["minimal_disambiguation", "criticism", "hard_negative", "ordinary"],
        workers=1,
        mock_client=mock_client
    )

    print(f"\n[✓] Project B completed: {res_b['total_candidates']} candidate variants generated.")
    print(f"    Exported files in: {out_dir_b}")
    for fname, path in res_b["exported_files"].items():
        size = os.path.getsize(path) if os.path.exists(path) else 0
        print(f"      - {fname}: {os.path.basename(path)} ({size} bytes)")

    # Read summary B
    summary_b_path = res_b["exported_files"]["summary_json"]
    with open(summary_b_path, "r", encoding="utf-8") as f:
        summary_b = json.load(f)
    print(f"\n    Summary B:")
    print(f"      Total Candidates: {summary_b['total_candidates_generated']}")
    print(f"      Accepted White:   {summary_b['accepted_white_count']}")
    print(f"      Review Queue:     {summary_b['review_queue_count']}")
    print(f"      Consensus breakdown: {summary_b['consensus_breakdown']}")

    print("\n" + "=" * 80)
    print("✅ OFFLINE DEMO COMPLETED SUCCESSFULLY WITH ZERO ERRORS.")
    print("   Authoritative JSONL files, human-ready CSVs, and Excel workbooks (.xlsx) are created.")
    print("=" * 80)


if __name__ == "__main__":
    run_full_offline_demo()
