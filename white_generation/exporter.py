"""
Multi-format exporter for Project B (White Generation).
Generates all 8 standard deliverable files with strict schema and formula defense.
"""
import os
import csv
import json
from typing import Dict, Any, List
from shared.text_safety import sanitize_for_excel
from shared.excel_utils import export_records_to_excel
from white_generation.storage import WhiteGenerationStorage


def write_jsonl(filepath: str, records: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_csv(filepath: str, records: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for r in records:
            row = []
            for field in fieldnames:
                val = r.get(field)
                if isinstance(val, (dict, list)):
                    val = json.dumps(val, ensure_ascii=False)
                row.append(sanitize_for_excel(val))
            writer.writerow(row)


def export_white_generation_outputs(
    storage: WhiteGenerationStorage,
    output_dir: str,
    run_id: str,
    config_dict: Dict[str, Any],
    lineage_report: Dict[str, Any]
) -> Dict[str, str]:
    """
    Exports all 8 standard deliverables for Project B.
    """
    os.makedirs(output_dir, exist_ok=True)
    all_candidates = storage.fetch_all_candidates()
    all_attempts = storage.fetch_all_attempts()

    standard_fields = [
        "id", "seed_id", "parent_id", "group_id", "split", "recipe",
        "origin", "generator_status", "candidate_text", "candidate_context",
        "seed_text", "seed_source_label", "persian_quality_score", "quality_status",
        "consensus_status", "final_label", "final_status", "judge_votes", "flags",
        "reason", "generator_model"
    ]

    # Subsets
    accepted_white = [c for c in all_candidates if c.get("final_status") == "accepted_white"]
    review_queue = [c for c in all_candidates if c.get("final_status") == "review_queue"]
    rejected_or_unresolved = [c for c in all_candidates if c.get("final_status") in ("rejected", "unresolved")]

    # 1. all_candidates
    f_all_jsonl = os.path.join(output_dir, "all_candidates.jsonl")
    f_all_csv = os.path.join(output_dir, "all_candidates.csv")
    write_jsonl(f_all_jsonl, all_candidates)
    write_csv(f_all_csv, all_candidates, standard_fields)

    # 2. accepted_white
    f_acc_w_jsonl = os.path.join(output_dir, "accepted_white.jsonl")
    f_acc_w_csv = os.path.join(output_dir, "accepted_white.csv")
    write_jsonl(f_acc_w_jsonl, accepted_white)
    write_csv(f_acc_w_csv, accepted_white, standard_fields)

    # 3. review_queue
    f_rev_csv = os.path.join(output_dir, "review_queue.csv")
    write_csv(f_rev_csv, review_queue, standard_fields)

    # 4. rejected_or_unresolved
    f_rej_jsonl = os.path.join(output_dir, "rejected_or_unresolved.jsonl")
    write_jsonl(f_rej_jsonl, rejected_or_unresolved)

    # 5. raw_responses
    f_raw_jsonl = os.path.join(output_dir, "raw_responses.jsonl")
    write_jsonl(f_raw_jsonl, all_attempts)

    # 6. summary.json
    total_tokens = sum(a.get("total_tokens", 0) for a in all_attempts)
    total_prompt_tokens = sum(a.get("prompt_tokens", 0) for a in all_attempts)
    total_comp_tokens = sum(a.get("completion_tokens", 0) for a in all_attempts)

    # Group counts by recipe
    recipe_counts = {}
    for c in all_candidates:
        r_name = c.get("recipe", "unknown")
        recipe_counts[r_name] = recipe_counts.get(r_name, 0) + 1

    summary_data = {
        "run_id": run_id,
        "total_candidates_generated": len(all_candidates),
        "accepted_white_count": len(accepted_white),
        "review_queue_count": len(review_queue),
        "rejected_or_unresolved_count": len(rejected_or_unresolved),
        "breakdown_by_recipe": recipe_counts,
        "consensus_breakdown": {
            "candidate0_unanimous": sum(1 for c in all_candidates if c.get("final_status") == "accepted_white"),
            "candidate0_split_3_1": sum(1 for c in all_candidates if "split_3_1" in (c.get("flags") or [])),
            "candidate1_offensive": sum(1 for c in all_candidates if c.get("consensus_status") == "candidate1"),
            "tie_2_2": sum(1 for c in all_candidates if c.get("consensus_status") == "tie_2_2"),
            "unresolved": sum(1 for c in all_candidates if c.get("consensus_status") == "unresolved")
        },
        "total_api_calls_logged": len(all_attempts),
        "tokens_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_comp_tokens,
            "total_tokens": total_tokens
        }
    }
    f_summary = os.path.join(output_dir, "summary.json")
    with open(f_summary, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # 7. manifest.json
    manifest_data = {
        "manifest_version": "1.0",
        "pipeline": "white_generation",
        "run_id": run_id,
        "config": {k: v for k, v in config_dict.items() if not str(k).lower().endswith("key")},
        "lineage_report": lineage_report,
        "exported_files": [
            "all_candidates.jsonl", "all_candidates.csv",
            "accepted_white.jsonl", "accepted_white.csv",
            "review_queue.csv", "rejected_or_unresolved.jsonl",
            "raw_responses.jsonl", "summary.json", "manifest.json", "review.xlsx"
        ]
    }
    f_manifest = os.path.join(output_dir, "manifest.json")
    with open(f_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    # 8. review.xlsx
    f_review_xlsx = os.path.join(output_dir, "review.xlsx")
    export_records_to_excel(
        records=all_candidates,
        output_path=f_review_xlsx,
        sheet_title="White Generation Review",
        include_hitl_columns=True
    )

    return {
        "all_candidates_jsonl": f_all_jsonl,
        "all_candidates_csv": f_all_csv,
        "accepted_white_jsonl": f_acc_w_jsonl,
        "accepted_white_csv": f_acc_w_csv,
        "review_queue_csv": f_rev_csv,
        "rejected_or_unresolved_jsonl": f_rej_jsonl,
        "raw_responses_jsonl": f_raw_jsonl,
        "summary_json": f_summary,
        "manifest_json": f_manifest,
        "review_xlsx": f_review_xlsx
    }
