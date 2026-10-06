"""
Command-Line Interface (CLI) and Orchestrator for Project A: Persianization.
Features:
- Streaming batch execution with bounded memory footprint
- Dual quality evaluation with random and targeted secondary adjudication
- Automated fallback on covert censorship or critical quality failure
- Standalone context translation for Native Persian records
- Circuit breaker for error spike detection and graceful pause
- Independent concurrency and rate limiting
"""
import os
import sys
import uuid
import signal
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Generator, Callable, Set

from shared.io_utils import stream_input_records, InputValidationError
from shared.lineage import LineageTracker
from shared.rate_limiter import RateLimiter, BudgetExceededError
from shared.circuit_breaker import PipelineCircuitBreaker, CircuitBreakerTripped
from shared.run_lock import RunDirectoryLock
from shared.api_client import AvalAIClient, AuthenticationError
from persianization.config import load_config, PersianizationConfig
from persianization.storage import PersianizationStorage
from persianization.router import route_record_languages
from persianization.translator import TranslationEngine
from persianization.quality_judge import DualQualityJudge
from persianization.exporter import export_persianization_outputs
from persianization.review_manager import ingest_persianization_review
import hashlib


def compute_record_fingerprint(
    raw_text: str,
    raw_context: Optional[str],
    language: Optional[str],
    primary_model: str,
    prompt_hash: str,
    policy_hash: str
) -> str:
    """Deterministic SHA-256 fingerprint of input text, context, model, prompt, and policy."""
    parts = [
        raw_text or "",
        raw_context or "",
        language or "",
        primary_model or "",
        prompt_hash or "",
        policy_hash or ""
    ]
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()


def process_single_record(
    record: Dict[str, Any],
    router_fn,
    translator: TranslationEngine,
    quality_judge: DualQualityJudge,
    storage: PersianizationStorage,
    lineage_tracker: LineageTracker,
    circuit_breaker: PipelineCircuitBreaker,
    order_idx: int = 0
) -> Dict[str, Any]:
    """
    Processes a single record through routing, translation (with quality-triggered fallbacks),
    and dual quality evaluation.
    """
    rec_id = record["id"]
    raw_text = record["text"]
    raw_context = record.get("context")
    declared_lang = record.get("language")
    request_id = f"req_{uuid.uuid4().hex[:8]}"

    # Check circuit breaker health before executing
    circuit_breaker.check_healthy()

    # 1. Register lineage and verify family split
    lineage_tracker.register_record(
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

    # 3. Native Persian / Non-English Path
    if not requires_text_tr:
        if origin == "native_fa":
            translation_status = "not_required"
            quality_status = "not_evaluated"  # Explicitly not_evaluated
            final_fa_text = raw_text  # RAW TEXT DIRECT ENTRY

            # If Persian text has English context, translate context only!
            if requires_context_tr and raw_context:
                final_fa_context = translator.translate_context_only(
                    record_id=rec_id,
                    context_en=raw_context,
                    request_id=request_id
                )
                if final_fa_context is None:
                    # Context translation failed! Must not be silently hidden with null!
                    quality_status = "review_required"
                    reason = "English context translation failed; record held for review."
                    routing["text_lang_info"].setdefault("flags", []).append("context_translation_failed")
                else:
                    reason = "Direct Persian entry: context translated successfully."
            else:
                final_fa_context = raw_context
                reason = "Direct Persian entry: text translation not required."

            circuit_breaker.record_result()

        elif origin == "fingilish":
            translation_status = "uncertain"
            quality_status = "review_required"
            final_fa_text = None
            final_fa_context = None
            reason = "Fingilish detected: held for explicit review."
            circuit_breaker.record_result()
        else:
            translation_status = "uncertain"
            quality_status = "review_required"
            final_fa_text = None
            final_fa_context = None
            reason = f"Language uncertain: {routing['reason']}"
            circuit_breaker.record_result()

        prompt_hash = hashlib.sha256(translator.config.translator_prompt.encode("utf-8")).hexdigest()[:12]
        policy_hash = translator.config.policy_hash
        curr_fingerprint = compute_record_fingerprint(
            raw_text=raw_text,
            raw_context=raw_context,
            language=declared_lang,
            primary_model=translator.config.primary_model,
            prompt_hash=prompt_hash,
            policy_hash=policy_hash
        )

        result_row = {
            "id": rec_id,
            "input_order_idx": record.get("_input_order_idx", order_idx),
            "request_id": request_id,
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
            "evaluator_1_model": None,
            "quality_scores": None,
            "quality_flags": routing["text_lang_info"].get("flags", []),
            "reason": reason,
            "evaluator_2_model": None,
            "quality_scores_2": None,
            "quality_flags_2": None,
            "second_judge_reason": None,
            "second_judge_sampling_type": None,
            "disagreement_flag": False,
            "source": record.get("source"),
            "source_label": record.get("source_label"),
            "parent_id": record.get("parent_id"),
            "group_id": record["group_id"],
            "split": record["split"],
            "fingerprint": curr_fingerprint,
            "metadata": record.get("metadata", {})
        }
        storage.save_record(result_row)
        return result_row

    # 4. English Translation Path (with Quality-Triggered Fallbacks)
    total_candidate_models = 1 + len(translator.config.fallback_models)
    current_model_idx = 0
    final_qc_res = None
    final_tr_res = None

    fallback_trigger_flags = (
        "censored_content", "severity_changed", "meaning_changed", "target_changed",
        "stance_changed", "negation_changed", "quotation_changed", "ambiguity_changed",
        "ambiguity_resolved_by_guess", "context_distorted", "context_removed"
    )

    while current_model_idx < total_candidate_models:
        tr_res = translator.translate_record(
            record_id=rec_id,
            raw_text=raw_text,
            raw_context=raw_context,
            request_id=request_id,
            start_model_idx=current_model_idx
        )
        final_tr_res = tr_res
        current_model_idx = tr_res.get("model_idx", current_model_idx) + 1

        tr_status = tr_res["translation_status"]
        text_fa = tr_res.get("text_fa")
        context_fa = tr_res.get("context_fa")
        selected_model = tr_res.get("selected_model")
        used_fallback = tr_res.get("used_fallback", False)

        if tr_status == "translated" and text_fa:
            # Run dual quality evaluation
            qc_res = quality_judge.evaluate(
                record_id=rec_id,
                raw_text_en=raw_text,
                text_fa=text_fa,
                raw_context_en=raw_context,
                context_fa=context_fa,
                translator_model=selected_model,
                used_fallback=used_fallback,
                request_id=request_id
            )
            final_qc_res = qc_res

            # Fallback decision must inspect flags from BOTH Judge 1 and Judge 2!
            all_qc_flags = list(qc_res.get("flags") or []) + list(qc_res.get("quality_flags_2") or [])
            has_censorship_or_distortion = any(f in all_qc_flags for f in fallback_trigger_flags)

            # If censored or critical failure, and another fallback model exists, try next model!
            if has_censorship_or_distortion and current_model_idx < total_candidate_models:
                continue
            else:
                break
        else:
            # Model refused or failed
            break

    # 5. Finalize status from evaluation results
    if final_qc_res and final_tr_res and final_tr_res.get("text_fa"):
        final_quality_status = final_qc_res["quality_status"]
        final_fa_text = final_tr_res["text_fa"]
        final_fa_context = final_tr_res.get("context_fa")
        tr_status = final_tr_res["translation_status"]
        selected_model = final_tr_res.get("selected_model")
        reason = final_qc_res.get("reason")
        is_qual_failure = (final_quality_status in ("rejected", "review_required"))
        circuit_breaker.record_result(is_quality_failure=is_qual_failure)
    else:
        final_quality_status = "rejected"
        final_fa_text = None
        final_fa_context = None
        tr_status = final_tr_res.get("translation_status", "failed") if final_tr_res else "failed"
        selected_model = final_tr_res.get("selected_model") if final_tr_res else None
        reason = final_tr_res.get("reason", "Translation failed or refused.") if final_tr_res else "Failed."
        is_refusal = (tr_status in ("unable", "refused"))
        circuit_breaker.record_result(is_tech_error=(not is_refusal), is_refusal=is_refusal)

    prompt_hash = hashlib.sha256(translator.config.translator_prompt.encode("utf-8")).hexdigest()[:12]
    policy_hash = translator.config.policy_hash
    curr_fingerprint = compute_record_fingerprint(
        raw_text=raw_text,
        raw_context=raw_context,
        language=declared_lang,
        primary_model=translator.config.primary_model,
        prompt_hash=prompt_hash,
        policy_hash=policy_hash
    )

    result_row = {
        "id": rec_id,
        "input_order_idx": record.get("_input_order_idx", order_idx),
        "request_id": request_id,
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
        "evaluator_1_model": final_qc_res.get("evaluator_1_model") if final_qc_res else None,
        "quality_scores": final_qc_res.get("scores") if final_qc_res else None,
        "quality_flags": final_qc_res.get("flags") if final_qc_res else ["translation_failed"],
        "reason": reason,
        "evaluator_2_model": final_qc_res.get("evaluator_2_model") if final_qc_res else None,
        "quality_scores_2": final_qc_res.get("quality_scores_2") if final_qc_res else None,
        "quality_flags_2": final_qc_res.get("quality_flags_2") if final_qc_res else None,
        "second_judge_reason": final_qc_res.get("second_judge_reason") if final_qc_res else None,
        "second_judge_sampling_type": final_qc_res.get("second_judge_sampling_type") if final_qc_res else None,
        "disagreement_flag": final_qc_res.get("disagreement_flag", False) if final_qc_res else False,
        "source": record.get("source"),
        "source_label": record.get("source_label"),
        "parent_id": record.get("parent_id"),
        "group_id": record["group_id"],
        "split": record["split"],
        "fingerprint": curr_fingerprint,
        "metadata": record.get("metadata", {})
    }
    storage.save_record(result_row)
    return result_row


def batch_streamer(
    records_generator: Generator[Dict[str, Any], None, None],
    batch_size: int,
    completed_map: Dict[str, Dict[str, Any]],
    current_fingerprint_fn: Callable[[Dict[str, Any]], str],
    limit: Optional[int] = None
) -> Generator[List[Dict[str, Any]], None, None]:
    """Streams input records in manageable batches without loading full file into memory."""
    batch = []
    total_yielded = 0

    for original_order_idx, rec in enumerate(records_generator, start=1):
        rec["_input_order_idx"] = original_order_idx
        rec_id = rec["id"]

        if rec_id in completed_map:
            prev = completed_map[rec_id]
            # 1. If human has already reviewed/edited this record, NEVER overwrite
            if prev.get("human_decision") is not None and str(prev.get("human_decision")).strip() != "":
                continue
            # 2. Check if text, context, or config changed
            curr_fp = current_fingerprint_fn(rec)
            prev_fp = prev.get("fingerprint")
            if prev_fp == curr_fp:
                # Unmodified input and settings; skip
                continue

        batch.append(rec)
        total_yielded += 1

        if len(batch) >= batch_size:
            yield batch
            batch = []

        if limit and total_yielded >= limit:
            break

    if batch:
        yield batch


def run_pipeline(
    input_file: str,
    output_dir: str,
    env_file: Optional[str] = None,
    resume: bool = False,
    limit: Optional[int] = None,
    workers: Optional[int] = None,
    batch_size: Optional[int] = None,
    mock_client: Optional[AvalAIClient] = None
) -> Dict[str, Any]:
    """Runs the Persianization pipeline end-to-end with streaming batches and circuit breaker."""
    config = load_config(env_file)
    if output_dir:
        config.output_dir = output_dir

    # CLI args take precedence over env configuration
    if batch_size is not None and batch_size > 0:
        config.input_batch_size = batch_size

    effective_workers = workers if workers is not None and workers > 0 else config.max_concurrent_requests

    os.makedirs(config.output_dir, exist_ok=True)
    run_id = f"run_{uuid.uuid4().hex[:10]}"

    with RunDirectoryLock(config.output_dir):
        db_path = os.path.join(config.output_dir, "persianization_state.db")
        storage = PersianizationStorage(db_path)
        rate_limiter = RateLimiter(rpm=config.rpm, max_calls=config.max_api_calls)

        circuit_breaker = PipelineCircuitBreaker(
            max_failure_rate=config.circuit_breaker_max_failure_rate,
            min_observations=config.circuit_breaker_min_observations,
            enabled=config.circuit_breaker_enabled
        )

        client = mock_client or AvalAIClient(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            extra_headers=config.extra_headers,
            rate_limiter=rate_limiter
        )

        translator = TranslationEngine(config, client, storage)
        quality_judge = DualQualityJudge(config, client, storage)
        lineage_tracker = LineageTracker()

        # Pre-populate lineage tracker from existing DB records so resume maintains split history
        lineage_tracker.populate_from_records(storage.fetch_all_records())

        completed_map = storage.get_completed_records_map() if resume else {}
        max_workers = effective_workers
        effective_batch_size = config.input_batch_size

        print(f"[*] Starting Persianization Run: {run_id}")
        print(f"[*] Config: Batch Size={effective_batch_size}, Max Concurrent Workers={max_workers}")
        print(f"[*] Output directory: {config.output_dir}")

        processed_count = 0
        auth_error_occurred = False
        tripped_error = None
        global_order_idx = 0

        prompt_hash = hashlib.sha256(translator.config.translator_prompt.encode("utf-8")).hexdigest()[:12]
        policy_hash = translator.config.policy_hash
        def compute_fp(r: Dict[str, Any]) -> str:
            return compute_record_fingerprint(
                raw_text=r.get("text") or r.get("raw_text") or "",
                raw_context=r.get("context") or r.get("raw_context"),
                language=r.get("language") or r.get("original_language"),
                primary_model=translator.config.primary_model,
                prompt_hash=prompt_hash,
                policy_hash=policy_hash
            )

        # Stream batches
        raw_stream = stream_input_records(input_file)
        batches = batch_streamer(
            raw_stream,
            batch_size=effective_batch_size,
            completed_map=completed_map,
            current_fingerprint_fn=compute_fp,
            limit=limit
        )

        for batch_idx, batch in enumerate(batches, start=1):
            if circuit_breaker.is_tripped:
                print(f"[!] {circuit_breaker.trip_reason}. Halting batch processing.", file=sys.stderr)
                tripped_error = circuit_breaker.trip_reason
                break

            print(f"  --> Processing Batch #{batch_idx} ({len(batch)} records)...")

            if max_workers <= 1:
                for rec in batch:
                    try:
                        global_order_idx += 1
                        process_single_record(
                            record=rec,
                            router_fn=route_record_languages,
                            translator=translator,
                            quality_judge=quality_judge,
                            storage=storage,
                            lineage_tracker=lineage_tracker,
                            circuit_breaker=circuit_breaker,
                            order_idx=rec.get("_input_order_idx", global_order_idx)
                        )
                        processed_count += 1
                    except AuthenticationError as e:
                        print(f"[FATAL AUTH ERROR]: {e}", file=sys.stderr)
                        auth_error_occurred = True
                        break
                    except (BudgetExceededError, CircuitBreakerTripped) as e:
                        print(f"[*] Execution halted: {e}")
                        tripped_error = str(e)
                        break
                    except Exception as e:
                        print(f"[ERROR on record {rec.get('id')}]: {e}", file=sys.stderr)
            else:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {}
                    for rec in batch:
                        global_order_idx += 1
                        f = executor.submit(
                            process_single_record,
                            record=rec,
                            router_fn=route_record_languages,
                            translator=translator,
                            quality_judge=quality_judge,
                            storage=storage,
                            lineage_tracker=lineage_tracker,
                            circuit_breaker=circuit_breaker,
                            order_idx=rec.get("_input_order_idx", global_order_idx)
                        )
                        futures[f] = rec

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
                        except (BudgetExceededError, CircuitBreakerTripped) as e:
                            print(f"[*] Execution halted: {e}")
                            tripped_error = str(e)
                            executor.shutdown(wait=False, cancel_futures=True)
                            break
                        except Exception as e:
                            print(f"[ERROR on record {rec.get('id')}]: {e}", file=sys.stderr)

            if auth_error_occurred or tripped_error:
                break

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
            "circuit_breaker_stats": circuit_breaker.get_stats(),
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
    run_parser.add_argument("--workers", type=int, help="Concurrency workers limit")
    run_parser.add_argument("--concurrency", "-c", type=int, help="Concurrency workers limit (alias for --workers)")
    run_parser.add_argument("--batch-size", "-b", type=int, help="Batch chunk size for processing")

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
        concurrency = args.concurrency if args.concurrency is not None else args.workers
        if concurrency is not None and concurrency <= 0:
            parser.error("--concurrency / --workers must be a positive integer.")
        if args.batch_size is not None and args.batch_size <= 0:
            parser.error("--batch-size must be a positive integer.")

        run_pipeline(
            input_file=args.input,
            output_dir=args.output_dir,
            env_file=args.env_file,
            resume=args.resume,
            limit=args.limit,
            workers=concurrency,
            batch_size=args.batch_size
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
