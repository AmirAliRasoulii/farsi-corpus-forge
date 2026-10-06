"""
Unit tests for Project B (White Generation) consensus voting, HITL ingest, and project independence.
"""
import os
import openpyxl
from shared.api_client import AvalAIClient
from white_generation.config import load_white_config
from white_generation.storage import WhiteGenerationStorage
from white_generation.offense_judges import BlindOffensePanel
from white_generation.review_manager import ingest_white_generation_review
from mock_demo.mock_llm import mock_llm_handler


def test_offensive_candidate_blocked_from_accepted_white(tmp_path):
    """An offensive candidate must receive label 1 from panel and be rejected."""
    db_path = str(tmp_path / "test_offense_panel.db")
    storage = WhiteGenerationStorage(db_path)
    config = load_white_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    panel = BlindOffensePanel(config, client, storage)

    res = panel.evaluate_candidate(
        candidate_id="cand_test_off",
        candidate_text="تو یک بیشعور و احمق واقعی هستی!",
        recipe="ordinary"
    )

    assert res["consensus_status"] == "candidate1"
    assert res["final_label"] == 1
    assert res["final_status"] == "rejected"
    assert "accepted_white" != res["final_status"]


def test_split_3_1_held_for_review(tmp_path):
    """A 3-1 split vote is marked candidate0 but held in review_queue until human confirmation."""
    db_path = str(tmp_path / "test_panel_split.db")
    storage = WhiteGenerationStorage(db_path)
    config = load_white_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    panel = BlindOffensePanel(config, client, storage)

    res = panel.evaluate_candidate(
        candidate_id="cand_split",
        candidate_text="متن تستی با رأی ۳ به ۱ [SIMULATE_SPLIT_3_1]",
        recipe="ordinary"
    )

    assert res["consensus_status"] == "candidate0"
    assert res["final_label"] == 0
    assert res["final_status"] == "review_queue"
    assert "split_3_1" in res["flags"]


def test_tie_2_2_held_for_review(tmp_path):
    """A 2-2 tie split vote is routed to review_queue."""
    db_path = str(tmp_path / "test_tie.db")
    storage = WhiteGenerationStorage(db_path)
    config = load_white_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    panel = BlindOffensePanel(config, client, storage)

    res = panel.evaluate_candidate(
        candidate_id="cand_tie",
        candidate_text="متن تستی تساوی دو به دو [SIMULATE_TIE_2_2]",
        recipe="ordinary"
    )

    assert res["consensus_status"] == "tie_2_2"
    assert res["final_label"] is None
    assert res["final_status"] == "review_queue"


def test_human_review_zero_distinct_from_blank(tmp_path):
    """HITL review must distinguish human decision '0' from blank unreviewed cell."""
    db_path = str(tmp_path / "test_hitl.db")
    storage = WhiteGenerationStorage(db_path)

    # Save initial candidate in review_queue
    cand = {
        "id": "cand_01",
        "seed_id": "seed_01",
        "parent_id": "seed_01",
        "group_id": "group_01",
        "split": "train",
        "seed_text": "بذر",
        "seed_source_label": 1,
        "recipe": "ordinary",
        "candidate_text": "متن کاندیدا",
        "candidate_context": None,
        "origin": "generated_white",
        "generator_status": "generated",
        "persian_quality_score": 5,
        "quality_status": "accepted",
        "judge_votes": {},
        "consensus_status": "tie_2_2",
        "final_label": None,
        "final_status": "review_queue",
        "flags": ["judge_tie_2_2"],
        "reason": "Tie",
        "generator_model": "gpt-4o-mini"
    }
    storage.save_candidate(cand)

    # Create dummy Excel with decision '0' (clean)
    excel_path = str(tmp_path / "review_test.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["id", "status", "human_decision", "human_edited_text", "human_notes", "reviewer_name"])
    ws.append(["cand_01", "review_queue", "0", "", "Clean confirmed by human", "annotator_1"])
    wb.save(excel_path)

    # Ingest review
    stats = ingest_white_generation_review(excel_path, storage)
    assert stats["updated_candidates_count"] == 1
    assert stats["accepted_white_count"] == 1

    # Verify candidate updated in SQLite
    updated = storage.fetch_all_candidates()[0]
    assert updated["final_status"] == "accepted_white"
    assert updated["final_label"] == 0
    assert updated["reviewer_name"] == "annotator_1"
