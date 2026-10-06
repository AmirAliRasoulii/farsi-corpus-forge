"""
Command-Line Interface (CLI) for Project A: Persianization.
Usage:
  python -m persianization.cli run --input dataset.csv --output-dir outputs/persianization
  python -m persianization.cli review-ingest --excel-file outputs/persianization/review.xlsx --output-dir outputs/persianization
  python -m persianization.cli export --output-dir outputs/persianization
"""
import os
import sys
import uuid
import signal
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional

from shared.io_utils import stream_input_records, InputValidationError
from shared.lineage import LineageTracker
from shared.rate_limiter import RateLimiter, BudgetExceededError
from shared.run_lock import RunDirectoryLock
from shared.api_client import AvalAIClient, AuthenticationError
from persianization.config import load_config, PersianizationConfig
from persianization.storage import PersianizationStorage
from persianization.router import route_record_languages
from persianization.translator import TranslationEngine
from persianization.quality_judge import QualityJudge
from persianization.exporter import export_persianization_outputs
from persianization.review_manager import ingest_persianization_review


def process_single_record(
    record: Dict[str, Any],
    router_fn,
    translator: TranslationEngine,
    quality_judge: QualityJudge,
    storage: PersianizationStorage,
    lineage_tracker: LineageTracker
) -> Dict[str, Any]:
    """Processes a single record through language routing, translation, and QC."""
    rec_id = record["id"]
    raw_text = record["text"]
    raw_context = record.get("context")
    declared_lang = record.get("language")

    # 1. Register lineage and check duplicates/split conflicts
    lineage_info = lineage_tracker.register_record(
        record_id=rec_id,
        text=raw_text,
        group_id=record["group_id"],
        split=record["split"],
        parent_id=record.get("parent_id")
    )

    # 2. Language Routing
    routing = router_fn(
        text=raw_text,
        context=raw_context,
        declared_language=declared_lang
    )

    origin = routing["origin"]
    requires_text_tr = routing["requires_text_translation"]
    requires_context_tr = routing["requires_context_translation"]

    # 3. Route Branching
    if not requires_text_tr:
        # Native Persian or Fingilish/Uncertain directly routed
        if origin == "native_fa":
            translation_status = "not_required"
            quality_status = "not_required"
            final_fa_text = raw_text  # RAW TEXT DIRECT ENTRY
            final_fa_context = raw_context
            reason = "Direct Persian entry: translator not called."
        elif origin == "fingilish":
            translation_status = "uncertain"
            quality_status = "review_required"
            final_fa_text = None
            final_fa_context = None
            reason = "Fingilish detected: held for explicit review."
        else:
            translation_status = "uncertain"
            quality_status = "review_required"
            final_fa_text = None
            final_fa_context = None
            reason = f"Language uncertain: {routing['reason']}"

        result_row = {
            "id": rec_id,
            "text": raw_text,
            "context": raw_context,
            "language": declared_lang or routing["text_lang_info"]["lang"],
            "origin": origin,
            "translation_status": translation_status,
            "quality_status": quality_status,
            "offense_label": None,
            "annotation_status": "not_annotated",
            "final_persian_text": final_fa_text,
            "final_persian_context": final_fa_context,
            "selected_model": None,
            "quality_scores": None,
            "quality_flags": routing["text_lang_info"].get("flags", []),
            "reason": reason,
            "source": record.get("source"),
            "source_label": record.get("source_label"),
            "parent_id": record.get("parent_id"),
            "group_id": record["group_id"],
            "split": record["split"],
            "metadata": record.get("metadata", {})
        }
        storage.save_record(result_row)
        return result_row

    # 4. Translation Branch (English to Persian)
    tr_res = translator.translate_record(
        record_id=rec_id,
        raw_text=raw_text,
        raw_context=raw_context
    )

    tr_status = tr_res["translation_status"]
    text_fa = tr_res.get("text_fa")
    context_fa = tr_res.get("context_fa")
    selected_model = tr_res.get("selected_model")

    if tr_status == "translated" and text_fa:
        # 5. Independent Quality Control Check
        qc_res = quality_judge.evaluate_translation(
            record_id=rec_id,
            raw_text_en=raw_text,
            text_fa=text_fa,
            raw_context_en=raw_context,
            context_fa=context_fa,
            translator_model=selected_model
        )

        final_quality_status = qc_res["quality_status"]
        quality_scores = qc_res.get("scores")
        quality_flags = qc_res.get("flags")
        reason = qc_res.get("reason")
        final_fa_text = text_fa
        final_fa_context = context_fa
    else:
        # Failed or unresolved translation
        final_quality_status = "rejected"
        quality_scores = None
        quality_flags = ["translation_unresolved"]
        reason = tr_res.get("reason", "Translation failed or refused.")
        final_fa_text = None
        final_fa_context = None

    result_row = {
        "id": rec_id,
        "text": raw_text,
        "context": raw_context,
        "language": declared_lang or "en",
        "origin": origin,
        "translation_status": tr_status,
        "quality_status": final_quality_status,
        "offense_label": None,
        "annotation_status": "not_annotated",
        "final_persian_text": final_fa_text,
        "final_persian_context": final_fa_context,
        "selected_model": selected_model,
        "quality_scores": quality_scores,
        "quality_flags": quality_flags,
        "reason": reason,
        "source": record.get("source"),
        "source_label": record.get("source_label"),
        "parent_id": record.get("parent_id"),
        "group_id": record["group_id"],
        "split": record["split"],
        "metadata": record.get("metadata", {})
    }
    storage.save_record(result_row)
    return result_row


def run_pipeline(
    input_file: str,
    output_dir: str,
    env_file: Optional[str] = None,
    resume: bool = False,
    limit: Optional[int] = None,
    workers: Optional[int] = None,
    mock_client: Optional[AvalAIClient] = None
) -> Dict[str, Any]:
    """Runs the Persianization pipeline end-to-end."""
    config = load_config(env_file)
    if output_dir:
        config.output_dir = output_dir

    os.makedirs(config.output_dir, exist_ok=True)
    run_id = f"run_{uuid.uuid4().hex[:10]}"

    with RunDirectoryLock(config.output_dir):
        db_path = os.path.join(config.output_dir, "persianization_state.db")
        storage = PersianizationStorage(db_path)
        rate_limiter = RateLimiter(rpm=config.rpm, max_calls=config.max_api_calls)

        client = mock_client or AvalAIClient(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            extra_headers=config.extra_headers,
            rate_limiter=rate_limiter
        )

        translator = TranslationEngine(config, client, storage)
        quality_judge = QualityJudge(config, client, storage)
        lineage_tracker = LineageTracker()

        completed_ids = storage.get_completed_ids() if resume else set()
        max_workers = workers if workers is not None else config.max_workers

        records_to_process = []
        for rec in stream_input_records(input_file):
            if resume and rec["id"] in completed_ids:
                continue
            records_to_process.append(rec)
            if limit and len(records_to_process) >= limit:
                break

        print(f"[*] Starting Persianization Run: {run_id}")
        print(f"[*] Records to process: {len(records_to_process)} (Resumed: {len(completed_ids)})")
        print(f"[*] Output directory: {config.output_dir}")

        processed_count = 0
        auth_error_occurred = False

        if max_workers <= 1:
            for rec in records_to_process:
                try:
                    process_single_record(
                        record=rec,
                        router_fn=route_record_languages,
                        translator=translator,
                        quality_judge=quality_judge,
                        storage=storage,
                        lineage_tracker=lineage_tracker
                    )
                    processed_count += 1
                except AuthenticationError as e:
                    print(f"[FATAL AUTH ERROR]: {e}", file=sys.stderr)
                    auth_error_occurred = True
                    break
                except BudgetExceededError as e:
                    print(f"[*] Budget limit reached: {e}")
                    break
                except Exception as e:
                    print(f"[ERROR on record {rec.get('id')}]: {e}", file=sys.stderr)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        process_single_record,
                        record=rec,
                        router_fn=route_record_languages,
                        translator=translator,
                        quality_judge=quality_judge,
                        storage=storage,
                        lineage_tracker=lineage_tracker
                    ): rec for rec in records_to_process
                }

                for future in as_completed(futures):
                    rec = futures[future]
                    try:
                        future.result()
                        processed_count += 1
                    except AuthenticationError as e:
                        print(f"[FATAL AUTH ERROR]: {e}", file=sys.stderr)
                        auth_error_occurred = True
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    except BudgetExceededError as e:
                        print(f"[*] Budget limit reached: {e}")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    except Exception as e:
                        print(f"[ERROR on record {rec.get('id')}]: {e}", file=sys.stderr)

        # Export outputs
        leakage_report = lineage_tracker.get_leakage_report()
        exported_files = export_persianization_outputs(
            storage=storage,
            output_dir=config.output_dir,
            run_id=run_id,
            config_dict=config.__dict__,
            leakage_report=leakage_report
        )

        print(f"[*] Completed Persianization Run: {run_id}")
        print(f"[*] Processed {processed_count} records. Deliverables exported to: {config.output_dir}")
        return {
            "run_id": run_id,
            "processed_count": processed_count,
            "exported_files": exported_files,
            "auth_error": auth_error_occurred,
            "leakage_report": leakage_report
        }


def main():
    parser = argparse.ArgumentParser(description="Persianization Research Pipeline (Project A)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Run Persianization pipeline")
    run_parser.add_argument("--input", "-i", required=True, help="Input CSV/JSON/JSONL file")
    run_parser.add_argument("--output-dir", "-o", default="outputs/persianization", help="Output directory")
    run_parser.add_argument("--env-file", "-e", help="Custom .env file path")
    run_parser.add_argument("--resume", action="store_true", help="Resume from existing checkpoint")
    run_parser.add_argument("--limit", type=int, help="Limit number of rows")
    run_parser.add_argument("--workers", type=int, help="Concurrency workers")

    # Subcommand: review-ingest
    ingest_parser = subparsers.add_parser("review-ingest", help="Ingest reviewed Excel spreadsheet")
    ingest_parser.add_argument("--excel-file", "-f", required=True, help="Path to reviewed Excel file")
    ingest_parser.add_argument("--output-dir", "-o", default="outputs/persianization", help="Output directory")
    ingest_parser.add_argument("--reviewer", "-r", default="human_annotator", help="Reviewer identifier")

    # Subcommand: export
    export_parser = subparsers.add_parser("export", help="Regenerate all exports from SQLite state")
    export_parser.add_argument("--output-dir", "-o", default="outputs/persianization", help="Output directory")

    args = parser.parse_args()

    if args.command == "run":
        run_pipeline(
            input_file=args.input,
            output_dir=args.output_dir,
            env_file=args.env_file,
            resume=args.resume,
            limit=args.limit,
            workers=args.workers
        )
    elif args.command == "review-ingest":
        db_path = os.path.join(args.output_dir, "persianization_state.db")
        storage = PersianizationStorage(db_path)
        stats = ingest_persianization_review(args.excel_file, storage, args.reviewer)
        print(f"[*] Ingest complete: {stats}")
        config = load_config()
        export_persianization_outputs(storage, args.output_dir, "review_update", config.__dict__, {})
    elif args.command == "export":
        db_path = os.path.join(args.output_dir, "persianization_state.db")
        storage = PersianizationStorage(db_path)
        config = load_config()
        export_persianization_outputs(storage, args.output_dir, "manual_export", config.__dict__, {})


if __name__ == "__main__":
    main()
