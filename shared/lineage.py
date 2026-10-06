"""
Provenance, lineage tracking, exact duplicate detection, and family split integrity.
Ensures records derived from the same source (family) maintain split consistency
and flags cross-split data leakage.
"""
import hashlib
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone


def compute_text_hash(text: str) -> str:
    """Computes SHA-256 hash of exact raw text."""
    if text is None:
        return ""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class LineageTracker:
    """
    Manages provenance tracking and detects exact duplicates and split leakage across families.
    """
    def __init__(self):
        # Maps text_hash -> list of record IDs
        self.exact_duplicate_map: Dict[str, List[str]] = {}
        # Maps group_id -> dict of {split: set of record IDs}
        self.group_split_map: Dict[str, Dict[str, Set[str]]] = {}
        # Stores detected family split discrepancies
        self.leakage_violations: List[Dict[str, Any]] = []

    def register_record(
        self,
        record_id: str,
        text: str,
        group_id: str,
        split: str,
        parent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Registers a record and checks for exact duplicates and split conflicts.
        """
        t_hash = compute_text_hash(text)
        if t_hash not in self.exact_duplicate_map:
            self.exact_duplicate_map[t_hash] = []
        self.exact_duplicate_map[t_hash].append(record_id)

        # Track family split
        if group_id not in self.group_split_map:
            self.group_split_map[group_id] = {}
        if split not in self.group_split_map[group_id]:
            self.group_split_map[group_id][split] = set()
        self.group_split_map[group_id][split].add(record_id)

        # Check if family now spans multiple splits
        distinct_splits = list(self.group_split_map[group_id].keys())
        has_split_conflict = len(distinct_splits) > 1

        if has_split_conflict and not any(v["group_id"] == group_id for v in self.leakage_violations):
            self.leakage_violations.append({
                "group_id": group_id,
                "splits": distinct_splits,
                "record_counts": {s: len(ids) for s, ids in self.group_split_map[group_id].items()},
                "warning": (
                    f"DATA LEAKAGE RISK: Family '{group_id}' spans multiple splits: {distinct_splits}. "
                    "Original and derived records must belong to the exact same dataset split."
                )
            })

        is_exact_duplicate = len(self.exact_duplicate_map[t_hash]) > 1
        duplicate_of = self.exact_duplicate_map[t_hash][0] if is_exact_duplicate else None

        return {
            "text_hash": t_hash,
            "is_exact_duplicate": is_exact_duplicate,
            "duplicate_of": duplicate_of,
            "has_split_conflict": has_split_conflict,
            "family_splits": distinct_splits
        }

    def get_leakage_report(self) -> Dict[str, Any]:
        """Returns summary of duplicates and split conflicts."""
        duplicates_count = sum(len(ids) - 1 for ids in self.exact_duplicate_map.values() if len(ids) > 1)
        return {
            "total_unique_text_hashes": len(self.exact_duplicate_map),
            "exact_duplicate_records_count": duplicates_count,
            "family_split_conflicts_count": len(self.leakage_violations),
            "split_violations": self.leakage_violations,
            "coverage_limitation_note": (
                "NOTE: Exact duplicate detection is based on verbatim SHA-256 text matching. "
                "Near-duplicate detection (e.g. MinHash/edit-distance) and semantic embedding similarity "
                "are complementary and not covered by exact hash comparison."
            )
        }


def build_lineage_metadata(
    original_id: str,
    output_id: str,
    source: Optional[str],
    source_version: Optional[str],
    original_text: str,
    original_language: Optional[str],
    origin: str,
    parent_id: Optional[str],
    group_id: str,
    split: str,
    model: Optional[str],
    prompt_version: Optional[str],
    run_id: str,
    config_snapshot: Dict[str, Any],
    source_label: Any = None,
    final_label_provenance: Optional[str] = None
) -> Dict[str, Any]:
    """Builds a standardized comprehensive lineage metadata dictionary."""
    return {
        "original_id": original_id,
        "output_id": output_id,
        "source": source or "unknown",
        "source_version": source_version or "v1.0",
        "original_language": original_language or "unknown",
        "origin": origin,
        "parent_id": parent_id,
        "group_id": group_id,
        "split": split or "unassigned",
        "model_used": model,
        "prompt_version": prompt_version or "v1",
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_label": source_label,
        "final_label_provenance": final_label_provenance,
        "config_snapshot": config_snapshot
    }
