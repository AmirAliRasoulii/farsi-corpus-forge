"""
Provenance, lineage tracking, exact duplicate detection, and family split integrity.
Ensures records derived from the same source (family) maintain split consistency
and flags cross-split data leakage.
"""
import hashlib
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone


import threading
import unicodedata

def compute_text_hash(text: str) -> str:
    """Computes SHA-256 hash of exact raw text."""
    if text is None:
        return ""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def normalize_text_view(text: str) -> str:
    """
    Auxiliary normalized representation for near/whitespace comparisons.
    Raw text is never mutated for downstream storage.
    """
    if not text:
        return ""
    norm = unicodedata.normalize("NFC", text.strip())
    return " ".join(norm.split())


class LineageTracker:
    """
    Manages provenance tracking and detects exact duplicates and split leakage across families and identical texts.
    Thread-safe for concurrent worker registration.
    """
    def __init__(self):
        self._lock = threading.Lock()
        # Maps text_hash -> list of record IDs
        self.exact_duplicate_map: Dict[str, List[str]] = {}
        # Maps text_hash -> dict of {split: set of record IDs}
        self.text_hash_split_map: Dict[str, Dict[str, Set[str]]] = {}
        # Maps group_id -> dict of {split: set of record IDs}
        self.group_split_map: Dict[str, Dict[str, Set[str]]] = {}
        # Stores detected family / text split discrepancies
        self.leakage_violations: List[Dict[str, Any]] = []

    def populate_from_records(self, records: List[Dict[str, Any]]) -> None:
        """Pre-populates tracker state from existing database records on resume."""
        with self._lock:
            for r in records:
                rec_id = r.get("id")
                txt = r.get("text") or r.get("final_persian_text") or r.get("raw_text")
                grp = r.get("group_id")
                splt = r.get("split")
                if rec_id and txt and grp and splt:
                    self._register_internal(
                        record_id=rec_id,
                        text=txt,
                        group_id=grp,
                        split=splt,
                        parent_id=r.get("parent_id")
                    )

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
        Thread-safe.
        """
        with self._lock:
            return self._register_internal(
                record_id=record_id,
                text=text,
                group_id=group_id,
                split=split,
                parent_id=parent_id
            )

    def _register_internal(
        self,
        record_id: str,
        text: str,
        group_id: str,
        split: str,
        parent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        t_hash = compute_text_hash(text)
        if t_hash not in self.exact_duplicate_map:
            self.exact_duplicate_map[t_hash] = []
        if record_id not in self.exact_duplicate_map[t_hash]:
            self.exact_duplicate_map[t_hash].append(record_id)

        # Track text split mapping across any group
        if t_hash not in self.text_hash_split_map:
            self.text_hash_split_map[t_hash] = {}
        if split not in self.text_hash_split_map[t_hash]:
            self.text_hash_split_map[t_hash][split] = set()
        self.text_hash_split_map[t_hash][split].add(record_id)

        # Track family group split mapping
        if group_id not in self.group_split_map:
            self.group_split_map[group_id] = {}
        if split not in self.group_split_map[group_id]:
            self.group_split_map[group_id][split] = set()
        self.group_split_map[group_id][split].add(record_id)

        # Check 1: Group / Family spans multiple splits
        distinct_family_splits = sorted(list(self.group_split_map[group_id].keys()))
        has_family_split_conflict = len(distinct_family_splits) > 1

        # Check 2: Identical text appears in different splits (cross-group leakage)
        distinct_text_splits = sorted(list(self.text_hash_split_map[t_hash].keys()))
        has_text_split_conflict = len(distinct_text_splits) > 1

        has_split_conflict = has_family_split_conflict or has_text_split_conflict

        if has_family_split_conflict:
            viol_key = f"family_{group_id}"
            if not any(v.get("violation_key") == viol_key for v in self.leakage_violations):
                self.leakage_violations.append({
                    "violation_key": viol_key,
                    "type": "family_split_conflict",
                    "group_id": group_id,
                    "splits": distinct_family_splits,
                    "record_counts": {s: len(ids) for s, ids in self.group_split_map[group_id].items()},
                    "warning": (
                        f"DATA LEAKAGE RISK: Family '{group_id}' spans multiple splits: {distinct_family_splits}. "
                        "Original and derived records must belong to the exact same dataset split."
                    )
                })

        if has_text_split_conflict:
            viol_key = f"text_{t_hash}"
            if not any(v.get("violation_key") == viol_key for v in self.leakage_violations):
                self.leakage_violations.append({
                    "violation_key": viol_key,
                    "type": "identical_text_cross_split_conflict",
                    "text_hash": t_hash,
                    "splits": distinct_text_splits,
                    "record_counts": {s: len(ids) for s, ids in self.text_hash_split_map[t_hash].items()},
                    "warning": (
                        f"DATA LEAKAGE RISK: Identical text (hash {t_hash[:10]}) appears in multiple splits: {distinct_text_splits} "
                        "across groups. Same text must not leak between train/val/test splits."
                    )
                })

        is_exact_duplicate = len(self.exact_duplicate_map[t_hash]) > 1
        duplicate_of = self.exact_duplicate_map[t_hash][0] if is_exact_duplicate else None

        return {
            "text_hash": t_hash,
            "is_exact_duplicate": is_exact_duplicate,
            "duplicate_of": duplicate_of,
            "has_split_conflict": has_split_conflict,
            "family_splits": distinct_family_splits,
            "text_splits": distinct_text_splits
        }

    def get_leakage_report(self) -> Dict[str, Any]:
        """Returns summary of duplicates and split conflicts."""
        with self._lock:
            duplicates_count = sum(len(ids) - 1 for ids in self.exact_duplicate_map.values() if len(ids) > 1)
            return {
                "total_unique_text_hashes": len(self.exact_duplicate_map),
                "exact_duplicate_records_count": duplicates_count,
                "family_split_conflicts_count": len(self.leakage_violations),
                "split_violations": list(self.leakage_violations),
                "has_blocking_leakage": len(self.leakage_violations) > 0,
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
