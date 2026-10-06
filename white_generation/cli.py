"""
Command-Line Interface (CLI) for Project B: White Generation.
Independent clean candidate generation and blinded 4-judge offense evaluation.
Usage:
  python -m white_generation.cli run --input seeds.jsonl --output-dir outputs/white_generation
  python -m white_generation.cli review-ingest --excel-file outputs/white_generation/review.xlsx
  python -m white_generation.cli export --output-dir outputs/white_generation
"""
import os
import sys
import uuid
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple, Set

from shared.io_utils import stream_input_records
from shared.lineage import LineageTracker
from shared.language_detector import detect_language
from shared.rate_limiter import RateLimiter, BudgetExceededError
from shared.run_lock import RunDirectoryLock
from shared.api_client import AvalAIClient, AuthenticationError
from white_generation.config import load_white_config, WhiteGenerationConfig
from white_generation.storage import WhiteGenerationStorage
from white_generation.recipes.generator import CandidateGenerator
from white_generation.quality_judge import WhiteQualityJudge
from white_generation.offense_judges import BlindOffensePanel
from white_generation.exporter import export_white_generation_outputs
from white_generation.review_manager import ingest_white_generation_review


def determine_seed_status(seed_record: Dict[str, Any]) -> str:
    """
    Distinguishes seed annotation statuses:
      - verified_offensive: label is 1
      - verified_non_offensive: label is 0
      - ambiguous_after_annotation: explicitly marked ambiguous
      - unannotated: label is None or unannotated (NOT ambiguous!)
    """
    lbl = seed_record.get("source_label")
    ann_status = seed_record.get("annotation_status")
    meta = seed_record.get("metadata") or {}

    if meta.get("category") == "ambiguous" or ann_status == "ambiguous":
        return "ambiguous_after_annotation"

    if lbl is not None and str(lbl).strip() != "":
        try:
            val = int(lbl)
            if val == 1:
                return "verified_offensive"
            elif val == 0:
                return "verified_non_offensive"
        except (ValueError, TypeError):
            pass

    return "unannotated"


def is_recipe_eligible(recipe_name: str, seed_status: str) -> Tuple[bool, str]:
    """
    Determines if a recipe is eligible for a given seed status.
    """
    if recipe_name == "criticism":
        if seed_status in ("verified_offensive", "ambiguous_after_annotation"):
            return True, "Eligible"
        return False, f"Criticism recipe requires offensive or ambiguous seed (got '{seed_status}')."

    if recipe_name == "minimal_disambiguation":
        if seed_status in ("ambiguous_after_annotation", "unannotated"):
            return True, "Eligible"
        return False, f"Disambiguation recipe requires ambiguous or unannotated seed (got '{seed_status}')."

    # hard_negative, ordinary, educational, reported_condemnation are applicable to all seed statuses
    return True, "Eligible"


def process_seed_and_generate(
    seed_record: Dict[str, Any],
    active_recipes: List[str],
    generator: CandidateGenerator,
    quality_judge: WhiteQualityJudge,
    offense_panel: BlindOffensePanel,
    storage: WhiteGenerationStorage,
    lineage_tracker: LineageTracker,
    completed_keys: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    """
    Processes a Persian seed across all active recipes.
    """
    seed_id = seed_record["id"]
    raw_text = seed_record["text"]
    group_id = seed_record.get("group_id") or seed_id
    split = seed_record.get("split", "unassigned")
    seed_status = determine_seed_status(seed_record)

    # Verify seed language is Persian
    lang_info = detect_language(raw_text, seed_record.get("language"))
    if lang_info["lang"] == "en":
        print(f"[SKIP SEED {seed_id}]: English seed provided to Project B. Route through Project A first.", file=sys.stderr)
        return []

    # Register lineage for seed
    lineage_tracker.register_record(
        record_id=seed_id,
        text=raw_text,
        group_id=group_id,
        split=split,
        parent_id=seed_record.get("parent_id")
    )

    generated_results = []

    for recipe_name in active_recipes:
        cand_id = f"cand_{seed_id}_{recipe_name}"
        if completed_keys and cand_id in completed_keys:
            # Already completed; skip to avoid re-invoking LLM
            continue

        # Check recipe eligibility
        eligible, reason_ineligible = is_recipe_eligible(recipe_name, seed_status)
        if not eligible:
            cand_row = {
                "id": cand_id,
                "seed_id": seed_id,
                "parent_id": seed_id,
                "group_id": group_id,
                "split": split,
                "seed_text": raw_text,
                "seed_source_label": seed_record.get("source_label"),
                "seed_status": seed_status,
                "recipe": recipe_name,
                "candidate_text": None,
                "candidate_context": None,
                "origin": "generated_white",
                "generator_status": "inapplicable",
                "persian_quality_score": None,
                "quality_status": "not_applicable",
                "judge_votes": None,
                "consensus_status": "inapplicable",
                "final_label": None,
                "final_status": "inapplicable",
                "flags": ["recipe_ineligible"],
                "reason": reason_ineligible,
                "generator_model": generator.config.generator_model
            }
            storage.save_candidate(cand_row)
            generated_results.append(cand_row)
            continue

        # 1. Generate candidate
        gen_res = generator.generate_candidate(
            candidate_id=cand_id,
            seed_record=seed_record,
            recipe_key=recipe_name
        )

        gen_status = gen_res.get("generator_status")
        cand_text = gen_res.get("candidate_text")
        cand_context = gen_res.get("candidate_context")

        if gen_status == "inapplicable":
            cand_row = {
                "id": cand_id,
                "seed_id": seed_id,
                "parent_id": seed_id,
                "group_id": group_id,
                "split": split,
                "seed_text": raw_text,
                "seed_source_label": seed_record.get("source_label"),
                "seed_status": seed_status,
                "recipe": recipe_name,
                "candidate_text": None,
                "candidate_context": None,
                "origin": "generated_white",
                "generator_status": "inapplicable",
                "persian_quality_score": None,
                "quality_status": "not_applicable",
                "judge_votes": None,
                "consensus_status": "inapplicable",
                "final_label": None,
                "final_status": "inapplicable",
                "flags": ["inapplicable_seed"],
                "reason": gen_res.get("reason", "Recipe inapplicable"),
                "generator_model": generator.config.generator_model
            }
            storage.save_candidate(cand_row)
            generated_results.append(cand_row)
            continue

        if gen_status != "generated" or not cand_text:
            cand_row = {
                "id": cand_id,
                "seed_id": seed_id,
                "parent_id": seed_id,
                "group_id": group_id,
                "split": split,
                "seed_text": raw_text,
                "seed_source_label": seed_record.get("source_label"),
                "seed_status": seed_status,
                "recipe": recipe_name,
                "candidate_text": None,
                "candidate_context": None,
                "origin": "generated_white",
                "generator_status": "failed",
                "persian_quality_score": None,
                "quality_status": "rejected",
                "judge_votes": None,
                "consensus_status": "unresolved",
                "final_label": None,
                "final_status": "unresolved",
                "flags": ["generation_failed"],
                "reason": gen_res.get("reason", "Generation failed"),
                "generator_model": generator.config.generator_model
            }
            storage.save_candidate(cand_row)
            generated_results.append(cand_row)
            continue

        # Register candidate in lineage
        lineage_tracker.register_record(
            record_id=cand_id,
            text=cand_text,
            group_id=group_id,
            split=split,
            parent_id=seed_id
        )

        # 2. Evaluate Persian quality
        qc_res = quality_judge.evaluate_candidate_quality(
            candidate_id=cand_id,
            candidate_text=cand_text,
            candidate_context=cand_context
        )

        quality_status = qc_res.get("quality_status")
        quality_score = qc_res.get("persian_quality_score")
        qc_flags = qc_res.get("flags", [])

        # 3. Blinded 4-Judge Offense Evaluation Panel
        panel_res = offense_panel.evaluate_candidate(
            candidate_id=cand_id,
            candidate_text=cand_text,
            candidate_context=cand_context,
            recipe=recipe_name
        )

        all_flags = qc_flags + panel_res.get("flags", [])
        final_status = panel_res.get("final_status", "unresolved")

        # If quality failed, override final status to rejected
        if quality_status == "rejected":
            final_status = "rejected"
            all_flags.append("low_persian_quality")
        elif quality_status == "review_required" and final_status == "accepted_white":
            final_status = "review_queue"
            all_flags.append("qc_review_required")

        cand_row = {
            "id": cand_id,
            "seed_id": seed_id,
            "parent_id": seed_id,
            "group_id": group_id,
            "split": split,
            "seed_text": raw_text,
            "seed_source_label": seed_record.get("source_label"),
            "seed_status": seed_status,
            "recipe": recipe_name,
            "candidate_text": cand_text,
            "candidate_context": cand_context,
            "origin": "generated_white",
            "generator_status": "generated",
            "persian_quality_score": quality_score,
            "quality_status": quality_status,
            "judge_votes": panel_res.get("judge_votes"),
            "consensus_status": panel_res.get("consensus_status"),
            "final_label": panel_res.get("final_label"),
            "final_status": final_status,
            "flags": all_flags,
            "reason": panel_res.get("reason", ""),
            "generator_model": generator.config.generator_model
        }
        storage.save_candidate(cand_row)
        generated_results.append(cand_row)

    return generated_results


def run_white_pipeline(
    input_file: str,
    output_dir: str,
    env_file: Optional[str] = None,
    resume: bool = False,
    limit: Optional[int] = None,
    recipes_filter: Optional[List[str]] = None,
    workers: Optional[int] = None,
    batch_size: Optional[int] = None,
    mock_client: Optional[AvalAIClient] = None
) -> Dict[str, Any]:
    """Runs the White Generation pipeline end-to-end with chunked streaming and blinded 4-judge evaluation."""
    config = load_white_config(env_file)
    if output_dir:
        config.output_dir = output_dir

    effective_workers = workers if workers is not None and workers > 0 else config.max_workers
    chunk_size = batch_size if batch_size is not None and batch_size > 0 else max(1, effective_workers * 2)

    os.makedirs(config.output_dir, exist_ok=True)
    run_id = f"run_{uuid.uuid4().hex[:10]}"

    with RunDirectoryLock(config.output_dir):
        db_path = os.path.join(config.output_dir, "white_generation_state.db")
        storage = WhiteGenerationStorage(db_path)
        rate_limiter = RateLimiter(rpm=config.rpm, max_calls=config.max_api_calls)

        client = mock_client or AvalAIClient(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            extra_headers=config.extra_headers,
            rate_limiter=rate_limiter
        )

        generator = CandidateGenerator(config, client, storage)
        quality_judge = WhiteQualityJudge(config, client, storage)
        offense_panel = BlindOffensePanel(config, client, storage)
        lineage_tracker = LineageTracker()

        # Pre-populate lineage tracker from existing database candidates
        lineage_tracker.populate_from_records(storage.fetch_all_candidates())

        active_recipes = recipes_filter or config.generation_policy.get("active_recipes", [
            "minimal_disambiguation", "criticism", "hard_negative", "ordinary"
        ])

        completed_keys = storage.get_completed_candidate_keys() if resume else set()

        print(f"[*] Starting White Generation Run: {run_id}")
        print(f"[*] Concurrency Workers: {effective_workers}, Chunk Size: {chunk_size}")
        print(f"[*] Active Recipes: {active_recipes}")
        print(f"[*] Output directory: {config.output_dir}")

        total_candidates_processed = 0

        # Helper to yield seeds in bounded chunks without loading full file into memory
        def chunk_streamer(stream, size, max_items):
            c = []
            count = 0
            for item in stream:
                c.append(item)
                count += 1
                if len(c) >= size:
                    yield c
                    c = []
                if max_items and count >= max_items:
                    break
            if c:
                yield c

        raw_seeds = stream_input_records(input_file)
        chunks = chunk_streamer(raw_seeds, chunk_size, limit)

        for chunk_idx, seed_chunk in enumerate(chunks, start=1):
            if effective_workers <= 1:
                for seed in seed_chunk:
                    try:
                        cands = process_seed_and_generate(
                            seed_record=seed,
                            active_recipes=active_recipes,
                            generator=generator,
                            quality_judge=quality_judge,
                            offense_panel=offense_panel,
                            storage=storage,
                            lineage_tracker=lineage_tracker,
                            completed_keys=completed_keys
                        )
                        total_candidates_processed += len(cands)
                    except AuthenticationError as e:
                        print(f"[FATAL AUTH ERROR]: {e}", file=sys.stderr)
                        break
                    except BudgetExceededError as e:
                        print(f"[*] Budget reached: {e}")
                        break
                    except Exception as e:
                        print(f"[ERROR on seed {seed.get('id')}]: {e}", file=sys.stderr)
            else:
                with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                    futures = {
                        executor.submit(
                            process_seed_and_generate,
                            seed_record=seed,
                            active_recipes=active_recipes,
                            generator=generator,
                            quality_judge=quality_judge,
                            offense_panel=offense_panel,
                            storage=storage,
                            lineage_tracker=lineage_tracker,
                            completed_keys=completed_keys
                        ): seed for seed in seed_chunk
                    }

                    for future in as_completed(futures):
                        seed = futures[future]
                        try:
                            cands = future.result()
                            total_candidates_processed += len(cands)
                        except AuthenticationError as e:
                            print(f"[FATAL AUTH ERROR]: {e}", file=sys.stderr)
                            executor.shutdown(wait=False, cancel_futures=True)
                            break
                        except BudgetExceededError as e:
                            print(f"[*] Budget reached: {e}")
                            executor.shutdown(wait=False, cancel_futures=True)
                            break
                        except Exception as e:
                            print(f"[ERROR on seed {seed.get('id')}]: {e}", file=sys.stderr)

        lineage_report = lineage_tracker.get_leakage_report()
        exported_files = export_white_generation_outputs(
            storage=storage,
            output_dir=config.output_dir,
            run_id=run_id,
            config_dict=config.__dict__,
            lineage_report=lineage_report
        )

        print(f"[*] White Generation Run Completed: {run_id}")
        print(f"[*] Total candidates processed: {total_candidates_processed}")
        print(f"[*] Deliverables exported to: {config.output_dir}")
        return {
            "run_id": run_id,
            "total_candidates": total_candidates_processed,
            "exported_files": exported_files,
            "lineage_report": lineage_report
        }


def main():
    parser = argparse.ArgumentParser(description="White Generation Pipeline (Project B)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Run White Generation pipeline")
    run_parser.add_argument("--input", "-i", required=True, help="Input Persian seed records (CSV/JSON/JSONL)")
    run_parser.add_argument("--output-dir", "-o", default="outputs/white_generation", help="Output directory")
    run_parser.add_argument("--env-file", "-e", help="Custom .env file path")
    run_parser.add_argument("--resume", action="store_true", help="Resume from existing checkpoint")
    run_parser.add_argument("--limit", type=int, help="Limit number of seed rows")
    run_parser.add_argument("--recipes", help="Comma-separated active recipes")
    run_parser.add_argument("--workers", type=int, help="Concurrency workers limit")
    run_parser.add_argument("--concurrency", "-c", type=int, help="Concurrency workers limit (alias for --workers)")
    run_parser.add_argument("--batch-size", "-b", type=int, help="Batch chunk size for processing")

    # Subcommand: review-ingest
    ingest_parser = subparsers.add_parser("review-ingest", help="Ingest reviewed Excel spreadsheet")
    ingest_parser.add_argument("--excel-file", "-f", required=True, help="Path to reviewed Excel file")
    ingest_parser.add_argument("--output-dir", "-o", default="outputs/white_generation", help="Output directory")
    ingest_parser.add_argument("--reviewer", "-r", default="human_annotator", help="Reviewer identifier")

    # Subcommand: export
    export_parser = subparsers.add_parser("export", help="Regenerate all exports from SQLite state")
    export_parser.add_argument("--output-dir", "-o", default="outputs/white_generation", help="Output directory")

    args = parser.parse_args()

    if args.command == "run":
        concurrency = args.concurrency if args.concurrency is not None else args.workers
        if concurrency is not None and concurrency <= 0:
            parser.error("--concurrency / --workers must be a positive integer.")
        if args.batch_size is not None and args.batch_size <= 0:
            parser.error("--batch-size must be a positive integer.")

        recipes_list = [r.strip() for r in args.recipes.split(",") if r.strip()] if args.recipes else None
        run_white_pipeline(
            input_file=args.input,
            output_dir=args.output_dir,
            env_file=args.env_file,
            resume=args.resume,
            limit=args.limit,
            recipes_filter=recipes_list,
            workers=concurrency,
            batch_size=args.batch_size
        )
    elif args.command == "review-ingest":
        db_path = os.path.join(args.output_dir, "white_generation_state.db")
        storage = WhiteGenerationStorage(db_path)
        stats = ingest_white_generation_review(args.excel_file, storage, args.reviewer)
        print(f"[*] Review Ingest complete: {stats}")
        config = load_white_config()
        export_white_generation_outputs(storage, args.output_dir, "review_update", config.__dict__, {})
    elif args.command == "export":
        db_path = os.path.join(args.output_dir, "white_generation_state.db")
        storage = WhiteGenerationStorage(db_path)
        config = load_white_config()
        export_white_generation_outputs(storage, args.output_dir, "manual_export", config.__dict__, {})


if __name__ == "__main__":
    main()
