"""
Unit tests for persistence, rate limits, checkpoint resumption, and lineage/leakage integrity.
"""
import pytest
from shared.rate_limiter import RateLimiter, BudgetExceededError
from shared.lineage import LineageTracker
from persianization.storage import PersianizationStorage


def test_rate_limiter_budget_exceeded():
    limiter = RateLimiter(rpm=0, max_calls=3)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()
    with pytest.raises(BudgetExceededError):
        limiter.acquire()


def test_family_split_leakage_detection():
    tracker = LineageTracker()

    # Original record in train
    tracker.register_record(
        record_id="rec_orig",
        text="Original text",
        group_id="family_101",
        split="train"
    )

    # Derived candidate erroneously put in dev
    res = tracker.register_record(
        record_id="cand_deriv",
        text="Derived text",
        group_id="family_101",
        split="dev"  # SPLIT MISMATCH!
    )

    assert res["has_split_conflict"] is True
    report = tracker.get_leakage_report()
    assert report["family_split_conflicts_count"] == 1
    assert "DATA LEAKAGE RISK" in report["split_violations"][0]["warning"]


def test_exact_duplicate_detection_preserves_records():
    tracker = LineageTracker()

    res1 = tracker.register_record(
        record_id="rec_1",
        text="Identical sentence",
        group_id="group_1",
        split="train"
    )
    assert res1["is_exact_duplicate"] is False

    res2 = tracker.register_record(
        record_id="rec_2",
        text="Identical sentence",
        group_id="group_2",
        split="train"
    )
    assert res2["is_exact_duplicate"] is True
    assert res2["duplicate_of"] == "rec_1"


def test_sqlite_checkpoint_and_resumption(tmp_path):
    db_path = str(tmp_path / "resume_test.db")
    storage = PersianizationStorage(db_path)

    # Save completed record
    rec1 = {
        "id": "rec_01",
        "text": "متن اول",
        "context": None,
        "language": "fa",
        "origin": "native_fa",
        "translation_status": "not_required",
        "quality_status": "not_required",
        "offense_label": None,
        "annotation_status": "not_annotated",
        "final_persian_text": "متن اول",
        "final_persian_context": None,
        "selected_model": None,
        "quality_scores": None,
        "quality_flags": [],
        "reason": "Direct",
        "source": "source",
        "source_label": 0,
        "parent_id": None,
        "group_id": "rec_01",
        "split": "train",
        "metadata": {}
    }
    storage.save_record(rec1)

    completed = storage.get_completed_ids()
    assert "rec_01" in completed
