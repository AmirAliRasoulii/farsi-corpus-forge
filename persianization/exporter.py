"""
Multi-format exporter for Project A (Persianization).
Generates all 10 standard output files with strict schema and formula protection.
"""
import os
import csv
import json
from typing import Dict, Any, List
from shared.text_safety import sanitize_for_excel
from shared.excel_utils import export_records_to_excel
from persianization.storage import PersianizationStorage


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


def export_persianization_outputs(
    storage: PersianizationStorage,
    output_dir: str,
    run_id: str,
    config_dict: Dict[str, Any],
    leakage_report: Dict[str, Any]
) -> Dict[str, str]:
    """
    Exports all 10 required deliverables for Project A.
    Returns dictionary mapping filename to path.
    """
    os.makedirs(output_dir, exist_ok=True)
    all_records = storage.fetch_all_records()
    all_attempts = storage.fetch_all_attempts()

    standard_fields = [
        "id", "origin", "translation_status", "quality_status",
        "offense_label", "annotation_status", "final_persian_text", "final_persian_context",
        "raw_text", "raw_context", "selected_model",
        "evaluator_1_model", "quality_scores", "quality_flags",
        "evaluator_2_model", "quality_scores_2", "quality_flags_2",
        "second_judge_sampling_type", "disagreement_flag",
        "reason", "source", "source_label", "parent_id", "group_id", "split"
    ]

    # Subsets
    native_fa_records = [r for r in all_records if r.get("origin") == "native_fa"]
    
    accepted_translations = [
        r for r in all_records 
        if r.get("origin") == "translated_en_to_fa" and r.get("quality_status") == "accepted"
    ]

    # accepted_persian includes BOTH native_fa and accepted translations
    accepted_persian = [
        r for r in all_records
        if (r.get("origin") == "native_fa") or 
           (r.get("origin") == "translated_en_to_fa" and r.get("quality_status") == "accepted")
    ]

    review_queue_records = [
        r for r in all_records
        if r.get("quality_status") in ("review_required", "pending_human_audit")
        or r.get("translation_status") in ("uncertain", "unable", "unresolved")
        or r.get("origin") in ("fingilish", "uncertain")
        or r.get("disagreement_flag") == 1
    ]

    failed_or_unresolved_records = [
        r for r in all_records
        if r.get("translation_status") in ("unresolved", "failed", "unable")
        or r.get("quality_status") == "rejected"
    ]

    # 1. all_records.jsonl & all_records.csv
    f_all_jsonl = os.path.join(output_dir, "all_records.jsonl")
    f_all_csv = os.path.join(output_dir, "all_records.csv")
    write_jsonl(f_all_jsonl, all_records)
    write_csv(f_all_csv, all_records, standard_fields)

    # 2. accepted_persian.jsonl & accepted_persian.csv
    f_acc_p_jsonl = os.path.join(output_dir, "accepted_persian.jsonl")
    f_acc_p_csv = os.path.join(output_dir, "accepted_persian.csv")
    write_jsonl(f_acc_p_jsonl, accepted_persian)
    write_csv(f_acc_p_csv, accepted_persian, standard_fields)

    # 3. native_fa.jsonl & native_fa.csv
    f_nat_jsonl = os.path.join(output_dir, "native_fa.jsonl")
    f_nat_csv = os.path.join(output_dir, "native_fa.csv")
    write_jsonl(f_nat_jsonl, native_fa_records)
    write_csv(f_nat_csv, native_fa_records, standard_fields)

    # 4. accepted_translations.jsonl & accepted_translations.csv
    f_acc_tr_jsonl = os.path.join(output_dir, "accepted_translations.jsonl")
    f_acc_tr_csv = os.path.join(output_dir, "accepted_translations.csv")
    write_jsonl(f_acc_tr_jsonl, accepted_translations)
    write_csv(f_acc_tr_csv, accepted_translations, standard_fields)

    # 5. review_queue.csv
    f_rev_csv = os.path.join(output_dir, "review_queue.csv")
    write_csv(f_rev_csv, review_queue_records, standard_fields)

    # 6. failed_or_unresolved.jsonl
    f_fail_jsonl = os.path.join(output_dir, "failed_or_unresolved.jsonl")
    write_jsonl(f_fail_jsonl, failed_or_unresolved_records)

    # 7. raw_responses.jsonl
    f_raw_jsonl = os.path.join(output_dir, "raw_responses.jsonl")
    write_jsonl(f_raw_jsonl, all_attempts)

    # 8. summary.json
    total_tokens = sum(a.get("total_tokens", 0) for a in all_attempts)
    total_prompt_tokens = sum(a.get("prompt_tokens", 0) for a in all_attempts)
    total_completion_tokens = sum(a.get("completion_tokens", 0) for a in all_attempts)

    summary_data = {
        "run_id": run_id,
        "total_records_processed": len(all_records),
        "native_fa_count": len(native_fa_records),
        "accepted_translations_count": len(accepted_translations),
        "total_accepted_persian_count": len(accepted_persian),
        "review_queue_count": len(review_queue_records),
        "failed_or_unresolved_count": len(failed_or_unresolved_records),
        "pending_human_audit_count": sum(1 for r in all_records if r.get("quality_status") == "pending_human_audit"),
        "second_judge_audits": {
            "total": sum(1 for r in all_records if r.get("evaluator_2_model")),
            "random_sample": sum(1 for r in all_records if r.get("second_judge_sampling_type") == "random_sample"),
            "targeted": sum(1 for r in all_records if str(r.get("second_judge_sampling_type") or "").startswith("targeted")),
            "disagreements": sum(1 for r in all_records if r.get("disagreement_flag") == 1)
        },
        "total_api_calls_logged": len(all_attempts),
        "tokens_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens
        },
        "breakdown_by_origin": {
            "native_fa": len(native_fa_records),
            "translated_en_to_fa": sum(1 for r in all_records if r.get("origin") == "translated_en_to_fa"),
            "fingilish": sum(1 for r in all_records if r.get("origin") == "fingilish"),
            "uncertain": sum(1 for r in all_records if r.get("origin") == "uncertain")
        }
    }
    f_summary = os.path.join(output_dir, "summary.json")
    with open(f_summary, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # 9. manifest.json
    manifest_data = {
        "manifest_version": "1.0",
        "pipeline": "persianization",
        "run_id": run_id,
        "config": {k: v for k, v in config_dict.items() if not str(k).lower().endswith("key")},
        "data_leakage_and_lineage_report": leakage_report,
        "exported_files": [
            "all_records.jsonl", "all_records.csv",
            "accepted_persian.jsonl", "accepted_persian.csv",
            "native_fa.jsonl", "native_fa.csv",
            "accepted_translations.jsonl", "accepted_translations.csv",
            "review_queue.csv", "failed_or_unresolved.jsonl",
            "raw_responses.jsonl", "summary.json", "manifest.json", "review.xlsx"
        ]
    }
    f_manifest = os.path.join(output_dir, "manifest.json")
    with open(f_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    # 10. review.xlsx
    f_review_xlsx = os.path.join(output_dir, "review.xlsx")
    export_records_to_excel(
        records=all_records,
        output_path=f_review_xlsx,
        sheet_title="Persianization Review",
        include_hitl_columns=True
    )

    return {
        "all_records_jsonl": f_all_jsonl,
        "all_records_csv": f_all_csv,
        "accepted_persian_jsonl": f_acc_p_jsonl,
        "accepted_persian_csv": f_acc_p_csv,
        "native_fa_jsonl": f_nat_jsonl,
        "native_fa_csv": f_nat_csv,
        "accepted_translations_jsonl": f_acc_tr_jsonl,
        "accepted_translations_csv": f_acc_tr_csv,
        "review_queue_csv": f_rev_csv,
        "failed_or_unresolved_jsonl": f_fail_jsonl,
        "raw_responses_jsonl": f_raw_jsonl,
        "summary_json": f_summary,
        "manifest_json": f_manifest,
        "review_xlsx": f_review_xlsx
    }
