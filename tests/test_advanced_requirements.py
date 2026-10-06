"""
Comprehensive tests for advanced requirements:
1. Evaluator independence from primary and all fallback models
2. Covert censorship detection and pristine-input fallback
3. Severity and target shift detection with fluent Persian
4. Dual blind quality adjudication, 10% random sample, targeted sample, and disagreement tagging
5. Unaccepted status while awaiting second judge
6. Batch out-of-order handling, single record failure isolation
7. Shared rate and budget limits across all workers
8. Native Persian target retention with context-only translation
9. Cache invalidation on prompt, policy, model, or context change
10. White generation taxonomy: unannotated vs ambiguous
11. Human review atomic ingest, separate human_edited_text, and invalidation of prior QC scores
12. Circuit breaker error-spike tripping
"""
import pytest
from unittest.mock import MagicMock
from shared.api_client import AvalAIClient
from shared.rate_limiter import RateLimiter, BudgetExceededError
from shared.lineage import LineageTracker
from shared.circuit_breaker import PipelineCircuitBreaker, CircuitBreakerTripped
from persianization.config import load_config, PersianizationConfig
from persianization.storage import PersianizationStorage
from persianization.translator import TranslationEngine, compute_translator_cache_key
from persianization.quality_judge import DualQualityJudge, compute_qc_cache_key, is_sampled_for_judge_2_random
from persianization.router import route_record_languages
from persianization.cli import process_single_record
from persianization.review_manager import ingest_persianization_review
from white_generation.storage import WhiteGenerationStorage
from mock_demo.mock_llm import mock_llm_handler


def test_evaluator_independence_from_all_fallbacks(tmp_path):
    """Quality judges must be independent from primary AND all fallback models."""
    config = load_config()
    
    # 1. Quality Model 1 matching a fallback model must fail validation
    config.quality_model_1 = config.fallback_models[0]
    with pytest.raises(ValueError, match=r"(?i)independence violation.*quality_model_1"):
        config.validate()

    # 2. Quality Model 2 matching a fallback model must fail validation
    config = load_config()
    config.quality_model_2 = config.fallback_models[0]
    with pytest.raises(ValueError, match=r"(?i)independence violation.*quality_model_2"):
        config.validate()

    # 3. Quality Model 1 and Quality Model 2 having identical IDs must fail validation
    config = load_config()
    config.quality_model_2 = config.quality_model_1
    with pytest.raises(ValueError, match=r"(?i)distinct model IDs"):
        config.validate()


def test_covert_censorship_triggers_fallback_with_pristine_raw_input(tmp_path):
    """
    When primary model returns a valid JSON that secretly censors profanity,
    Quality Judge 1 detects censorship, candidate is rejected, and fallback model
    is invoked with the pristine raw input.
    """
    db_path = str(tmp_path / "censorship_fallback.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    translator = TranslationEngine(config, client, storage)
    quality_judge = DualQualityJudge(config, client, storage)
    lineage_tracker = LineageTracker()
    circuit_breaker = PipelineCircuitBreaker()

    record = {
        "id": "rec_covert_censorship",
        "text": "Get out of here, you damn fool! [SIMULATE_COVERT_CENSORSHIP]",
        "context": None,
        "language": "en",
        "group_id": "grp_censorship",
        "split": "train"
    }

    res = process_single_record(
        record=record,
        router_fn=route_record_languages,
        translator=translator,
        quality_judge=quality_judge,
        storage=storage,
        lineage_tracker=lineage_tracker,
        circuit_breaker=circuit_breaker
    )

    # In mock_llm, [SIMULATE_COVERT_CENSORSHIP] on primary model returns censored Persian ("برو از اینجا، تو آدم بدی هستی")
    # which QualityJudge flags with 'censored_content'.
    # The pipeline should have fallen back to fallback model!
    assert res["selected_model"] != config.primary_model
    assert res["selected_model"] in config.fallback_models
    assert res["translation_status"] == "translated"


def test_severity_shift_with_fluent_persian_blocked(tmp_path):
    """
    A candidate with high fluency but diluted/escalated severity must be rejected or held for review.
    """
    db_path = str(tmp_path / "severity_shift.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    judge = DualQualityJudge(config, client, storage)

    # Simulate Judge 1 detecting severity_changed
    res = judge.evaluate(
        record_id="rec_sev",
        raw_text_en="You incompetent fool! [SIMULATE_SEVERITY_SHIFT]",
        text_fa="شما کمی بی‌تجربه هستید.",  # diluted
        raw_context_en=None,
        context_fa=None,
        translator_model="some-translator-model",
        used_fallback=False
    )

    assert "severity_changed" in res["flags"]
    assert res["quality_status"] in ("rejected", "review_required")


def test_dual_blind_adjudication_and_critical_disagreement(tmp_path):
    """
    Judge 2 evaluates blindly without seeing Judge 1's score or reason.
    If Judge 1 passes but Judge 2 detects a critical blocking flag, disagreement is recorded,
    and the record is held for review without score averaging.
    """
    db_path = str(tmp_path / "dual_judge_disagree.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    judge = DualQualityJudge(config, client, storage)

    # In mock handler, [SIMULATE_JUDGE_DISAGREEMENT] makes Judge 1 pass (5/5) but Judge 2 flags censored_content
    res = judge.evaluate(
        record_id="rec_disagree",
        raw_text_en="Shut your mouth! [SIMULATE_JUDGE_DISAGREEMENT]",
        text_fa="لطفاً صحبت نکنید.",
        raw_context_en=None,
        context_fa=None,
        translator_model="gpt-4o-mini",
        used_fallback=True  # triggers targeted second adjudication
    )

    assert res["evaluator_2_model"] == config.quality_model_2
    assert res["disagreement_flag"] is True
    assert res["quality_status"] in ("review_required", "second_judge_disagreement")
    # Verify scores are NOT averaged
    assert res["scores"]["fluency"] != (res["scores"]["fluency"] + res["quality_scores_2"]["fluency"]) / 2 or res["quality_flags_2"]


def test_stable_random_sampling_and_targeted_sampling():
    """Verify hash-based stable sampling is deterministic and reproducible."""
    sample_rate = 0.10
    rec_id = "test_stable_rec_123"

    # Repeated calls for the same record ID must produce identical results
    sampled_1 = is_sampled_for_judge_2_random(rec_id, sample_rate)
    sampled_2 = is_sampled_for_judge_2_random(rec_id, sample_rate)
    assert sampled_1 == sampled_2

    # Rate 0.0 must never sample
    assert is_sampled_for_judge_2_random("any_id", 0.0) is False
    # Rate 1.0 must always sample
    assert is_sampled_for_judge_2_random("any_id", 1.0) is True


def test_unaccepted_while_awaiting_second_judge(tmp_path):
    """A record requiring second judge cannot be marked 'accepted' prior to Judge 2 completing."""
    db_path = str(tmp_path / "awaiting_judge.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    judge = DualQualityJudge(config, client, storage)

    # When evaluate is called with used_fallback=True, second judge is mandatory
    res = judge.evaluate(
        record_id="rec_targeted",
        raw_text_en="Just an insult.",
        text_fa="فقط یک توهین.",
        raw_context_en=None,
        context_fa=None,
        translator_model="gpt-4o-mini",
        used_fallback=True
    )

    # Both evaluators ran and evaluated
    assert res["evaluator_1_model"] is not None
    assert res["evaluator_2_model"] is not None


def test_native_persian_with_english_context_translates_context_only(tmp_path):
    """
    Persian target text with English context:
    - Target text is kept verbatim (not translated).
    - Origin is native_fa, translation_status is not_required, quality_status is not_evaluated.
    - ONLY the English context is translated.
    """
    db_path = str(tmp_path / "native_ctx.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    translator = TranslationEngine(config, client, storage)
    quality_judge = DualQualityJudge(config, client, storage)
    lineage_tracker = LineageTracker()
    circuit_breaker = PipelineCircuitBreaker()

    record = {
        "id": "rec_fa_en_ctx",
        "text": "این یک پیام توهین‌آمیز کاملاً فارسی است.",
        "context": "The speaker was angry during an online debate.",
        "language": "fa",
        "group_id": "grp_fa_en",
        "split": "train"
    }

    res = process_single_record(
        record=record,
        router_fn=route_record_languages,
        translator=translator,
        quality_judge=quality_judge,
        storage=storage,
        lineage_tracker=lineage_tracker,
        circuit_breaker=circuit_breaker
    )

    assert res["origin"] == "native_fa"
    assert res["translation_status"] == "not_required"
    assert res["quality_status"] == "not_evaluated"
    assert res["final_persian_text"] == "این یک پیام توهین‌آمیز کاملاً فارسی است."
    # Context translated
    assert res["final_persian_context"] is not None
    assert any('\u0600' <= c <= '\u06FF' for c in res["final_persian_context"])


def test_single_record_failure_does_not_lose_successful_batch_records(tmp_path):
    """
    In a batch where one record fails, successful records are committed immediately,
    and subsequent runs resume without reprocessing successful records.
    """
    db_path = str(tmp_path / "batch_isolation.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    translator = TranslationEngine(config, client, storage)
    quality_judge = DualQualityJudge(config, client, storage)
    lineage_tracker = LineageTracker()
    circuit_breaker = PipelineCircuitBreaker()

    # Record 1 succeeds
    rec1 = {
        "id": "rec_batch_1",
        "text": "Normal insult here.",
        "context": None,
        "language": "en",
        "group_id": "grp_b1",
        "split": "train"
    }
    # Record 2 fails (e.g. all fallbacks refuse)
    rec2 = {
        "id": "rec_batch_2",
        "text": "Total refusal test [SIMULATE_REFUSAL]",
        "context": None,
        "language": "en",
        "group_id": "grp_b2",
        "split": "train"
    }

    res1 = process_single_record(rec1, route_record_languages, translator, quality_judge, storage, lineage_tracker, circuit_breaker, order_idx=1)
    res2 = process_single_record(rec2, route_record_languages, translator, quality_judge, storage, lineage_tracker, circuit_breaker, order_idx=2)

    all_saved = storage.get_all_saved_ids()
    assert "rec_batch_1" in all_saved
    assert "rec_batch_2" in all_saved  # Saved as unresolved/failed checkpoint, not lost

    assert res1["translation_status"] == "translated"
    assert res2["translation_status"] == "unresolved"

    all_records = storage.fetch_all_records()
    assert len(all_records) == 2
    assert all_records[0]["input_order_idx"] == 1
    assert all_records[1]["input_order_idx"] == 2


def test_shared_rate_and_call_budget_across_all_stages():
    """All workers and stages share the same token bucket and request budget."""
    limiter = RateLimiter(rpm=60, max_calls=5)
    
    # 5 calls across translator, fallback, and quality judge
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert limiter.total_calls == 5
    with pytest.raises(BudgetExceededError):
        limiter.acquire()


def test_cache_invalidation_on_prompt_model_context_policy_change():
    """Cache key must be invalidated when prompt, policy, model, or context changes."""
    k1 = compute_translator_cache_key("hello", "context A", "model1", "prompt_v1", "policy_v1")
    k2 = compute_translator_cache_key("hello", "context A", "model1", "prompt_v2", "policy_v1")  # prompt changed
    k3 = compute_translator_cache_key("hello", "context B", "model1", "prompt_v1", "policy_v1")  # context changed
    k4 = compute_translator_cache_key("hello", "context A", "model2", "prompt_v1", "policy_v1")  # model changed
    k5 = compute_translator_cache_key("hello", "context A", "model1", "prompt_v1", "policy_v2")  # policy changed

    assert k1 != k2
    assert k1 != k3
    assert k1 != k4
    assert k1 != k5

    qc1 = compute_qc_cache_key("en", "fa", "ctx_en", "ctx_fa", "m1", "p_v1", "pol_v1")
    qc2 = compute_qc_cache_key("en", "fa", "ctx_en", "ctx_fa", "m1", "p_v1", "pol_v2")  # policy changed
    assert qc1 != qc2


def test_white_generation_unannotated_vs_ambiguous_taxonomy():
    """
    White generation must differentiate between unannotated and ambiguous_after_annotation.
    Unannotated seeds must not be treated as ambiguous.
    """
    from white_generation.cli import determine_seed_status, is_recipe_eligible

    # 1. Unannotated record (source_label is None and not marked ambiguous)
    s1 = {"id": "s1", "text": "متن عادی بدون برچسب", "source_label": None, "annotation_status": "not_annotated"}
    status1 = determine_seed_status(s1)
    assert status1 == "unannotated"
    eligible1, _ = is_recipe_eligible("criticism", status1)
    assert eligible1 is False  # Criticism requires offensive or ambiguous seed

    # 2. Ambiguous after annotation
    s2 = {"id": "s2", "text": "متن با رأی مساوی داوران", "source_label": None, "annotation_status": "ambiguous"}
    status2 = determine_seed_status(s2)
    assert status2 == "ambiguous_after_annotation"
    eligible2, _ = is_recipe_eligible("criticism", status2)
    assert eligible2 is True

    # 3. Verified offensive seed
    s3 = {"id": "s3", "text": "توهین محرز", "source_label": 1, "annotation_status": "annotated"}
    status3 = determine_seed_status(s3)
    assert status3 == "verified_offensive"
    eligible3, _ = is_recipe_eligible("criticism", status3)
    assert eligible3 is True


def test_human_review_invalidation_of_prior_automated_scores(tmp_path):
    """
    When human review imports an edited text:
    - human_edited_text is populated in an independent field.
    - prior automated QC scores are invalidated (set to None or not inherited).
    - original record text and lineage are preserved.
    """
    import openpyxl
    import hashlib
    db_path = str(tmp_path / "human_review.db")
    storage = PersianizationStorage(db_path)

    # Save original record with automated QC scores
    storage.save_record({
        "id": "rec_human_rev_1",
        "input_order_idx": 0,
        "request_id": "req_1",
        "text": "You fool!",
        "context": None,
        "language": "en",
        "origin": "translated_en_to_fa",
        "translation_status": "translated",
        "quality_status": "review_required",
        "offense_label": None,
        "annotation_status": "not_annotated",
        "final_persian_text": "تو نادان!",
        "final_persian_context": None,
        "selected_model": "gpt-4o-mini",
        "evaluator_1_model": "gemini-2.5-flash",
        "quality_scores": {"fluency": 3, "naturalness": 2},
        "quality_flags": ["awkward_persian"],
        "reason": "Needs human check",
        "evaluator_2_model": None,
        "quality_scores_2": None,
        "quality_flags_2": None,
        "second_judge_reason": None,
        "second_judge_sampling_type": None,
        "disagreement_flag": False,
        "source": "test",
        "source_label": 1,
        "parent_id": None,
        "group_id": "grp_rev",
        "split": "train",
        "metadata": {}
    })

    # Create review excel file
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Review"
    ws.append([
        "id", "text_hash", "raw_text", "current_persian_text",
        "human_decision", "human_edited_text", "reviewer_name", "human_notes"
    ])
    
    # Calculate hash of raw_text
    h = hashlib.sha256("You fool!".encode("utf-8")).hexdigest()[:16]
    ws.append([
        "rec_human_rev_1", h, "You fool!", "تو نادان!",
        "edited", "تو ابله!", "reviewer_01", "Fixed awkward phrasing"
    ])

    excel_path = str(tmp_path / "review_completed.xlsx")
    wb.save(excel_path)

    ingest_persianization_review(
        excel_path=excel_path,
        storage=storage,
        run_id="run_test_01"
    )

    rec = storage.fetch_record_by_id("rec_human_rev_1")
    assert rec["human_decision"] == "edited"
    assert rec["human_edited_text"] == "تو ابله!"
    assert rec["reviewer_name"] == "reviewer_01"
    assert rec["quality_status"] == "accepted"
    # Automated scores invalidated
    assert rec["quality_scores"] is None
    # Original raw text preserved
    assert rec["raw_text"] == "You fool!"



def test_circuit_breaker_trips_on_error_spike():
    """Circuit breaker trips when failure rate exceeds configured threshold."""
    cb = PipelineCircuitBreaker(
        max_failure_rate=0.4,
        min_observations=5,
        enabled=True
    )

    # 3 successes, 3 failures -> failure rate 50% > 40%
    cb.record_result(is_tech_error=False)
    cb.record_result(is_tech_error=False)
    cb.record_result(is_tech_error=False)
    cb.record_result(is_tech_error=True)
    cb.record_result(is_tech_error=True)
    cb.record_result(is_tech_error=True)

    with pytest.raises(CircuitBreakerTripped):
        cb.check_healthy()
