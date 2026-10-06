"""
Shared modules for Persianization and White Generation research pipeline.
"""
from shared.text_safety import sanitize_for_excel, check_excel_length_limit, preserve_raw_text
from shared.language_detector import detect_language
from shared.io_utils import stream_input_records, InputValidationError, normalize_persian_nfc
from shared.lineage import LineageTracker, build_lineage_metadata, compute_text_hash
from shared.rate_limiter import RateLimiter, BudgetExceededError
from shared.run_lock import RunDirectoryLock
from shared.api_client import AvalAIClient, AuthenticationError, ModelRefusalError, extract_json_from_completion
from shared.excel_utils import export_records_to_excel, read_reviewed_excel
