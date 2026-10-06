"""
Configuration loader for Persianization pipeline.
Validates model independence and parses environment settings.
"""
import os
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv


@dataclass
class PersianizationConfig:
    # API credentials and endpoints
    api_key: str
    base_url: str
    extra_headers: Dict[str, str]

    # Translation models
    primary_model: str
    fallback_models: List[str]
    quality_model: str

    # Model parameters
    translator_route: str
    translator_output_mode: str
    translator_max_tokens: int
    translator_token_field: str
    translator_temperature: float
    translator_extra_json: Dict[str, Any]

    quality_route: str
    quality_output_mode: str
    quality_max_tokens: int
    quality_token_field: str
    quality_temperature: float
    quality_extra_json: Dict[str, Any]

    # Worker controls
    max_workers: int
    timeout: int
    max_retries: int
    rpm: int
    max_api_calls: int

    # Quality policy
    quality_accept_threshold: float
    human_audit_sample_rate: float
    review_policy: Dict[str, Any]

    # Prompts
    translator_prompt: str
    quality_prompt: str
    prompt_version: str = "v1.0"
    output_dir: str = "outputs/persianization"

    def validate(self) -> None:
        """Validates critical constraints."""
        if not self.primary_model:
            raise ValueError("TRANSLATOR_PRIMARY_MODEL must be configured.")
        if not self.quality_model:
            raise ValueError("QUALITY_MODEL must be configured.")
        if self.primary_model.strip() == self.quality_model.strip():
            raise ValueError(
                f"INDEPENDENCE VIOLATION: Primary translator model and QUALITY_MODEL are identical ('{self.primary_model}'). "
                "Quality evaluation MUST be performed by an independent model."
            )


def load_config(env_path: Optional[str] = None) -> PersianizationConfig:
    """Loads configuration from environment / .env file."""
    if env_path and os.path.exists(env_path):
        load_dotenv(env_path, override=True)
    else:
        # Load from default .env if exists
        load_dotenv()

    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.avalai.ir/v1")
    
    extra_headers_str = os.getenv("EXTRA_HEADERS", "{}")
    try:
        extra_headers = json.loads(extra_headers_str)
    except Exception:
        extra_headers = {}

    primary_model = os.getenv("TRANSLATOR_PRIMARY_MODEL", "gpt-4o-mini").strip()
    fallbacks_raw = os.getenv("TRANSLATOR_FALLBACK_MODELS", "claude-haiku-4-5,gemini-2.5-flash,deepseek-chat")
    fallback_models = [m.strip() for m in fallbacks_raw.split(",") if m.strip()]

    quality_model = os.getenv("QUALITY_MODEL", "deepseek-chat").strip()

    # Prompts
    prompt_tr_path = os.getenv("PROMPT_TRANSLATOR_FILE", "persianization/prompts/translator_prompt.md")
    prompt_ql_path = os.getenv("PROMPT_QUALITY_FILE", "persianization/prompts/quality_prompt.md")
    policy_path = os.getenv("REVIEW_POLICY_FILE", "persianization/config/review_policy.json")

    translator_prompt = ""
    if os.path.exists(prompt_tr_path):
        with open(prompt_tr_path, "r", encoding="utf-8") as f:
            translator_prompt = f.read()

    quality_prompt = ""
    if os.path.exists(prompt_ql_path):
        with open(prompt_ql_path, "r", encoding="utf-8") as f:
            quality_prompt = f.read()

    review_policy = {}
    if os.path.exists(policy_path):
        with open(policy_path, "r", encoding="utf-8") as f:
            review_policy = json.load(f)

    cfg = PersianizationConfig(
        api_key=api_key,
        base_url=base_url,
        extra_headers=extra_headers,
        primary_model=primary_model,
        fallback_models=fallback_models,
        quality_model=quality_model,
        translator_route=os.getenv("TRANSLATOR_API_ROUTE", "chat"),
        translator_output_mode=os.getenv("TRANSLATOR_OUTPUT_MODE", "json_object"),
        translator_max_tokens=int(os.getenv("TRANSLATOR_MAX_TOKENS", "4096")),
        translator_token_field=os.getenv("TRANSLATOR_TOKEN_FIELD", "max_completion_tokens"),
        translator_temperature=float(os.getenv("TRANSLATOR_TEMPERATURE", "0.1")),
        translator_extra_json=json.loads(os.getenv("TRANSLATOR_EXTRA_JSON", "{}")),
        quality_route=os.getenv("QUALITY_API_ROUTE", "chat"),
        quality_output_mode=os.getenv("QUALITY_OUTPUT_MODE", "json_object"),
        quality_max_tokens=int(os.getenv("QUALITY_MAX_TOKENS", "4096")),
        quality_token_field=os.getenv("QUALITY_TOKEN_FIELD", "max_completion_tokens"),
        quality_temperature=float(os.getenv("QUALITY_TEMPERATURE", "0.0")),
        quality_extra_json=json.loads(os.getenv("QUALITY_EXTRA_JSON", "{}")),
        max_workers=int(os.getenv("MAX_WORKERS", "4")),
        timeout=int(os.getenv("REQUEST_TIMEOUT", "120")),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
        rpm=int(os.getenv("REQUESTS_PER_MINUTE", "0")),
        max_api_calls=int(os.getenv("MAX_API_CALLS", "0")),
        quality_accept_threshold=float(os.getenv("QUALITY_ACCEPT_THRESHOLD", str(review_policy.get("min_dimension_score", 4.0)))),
        human_audit_sample_rate=float(os.getenv("HUMAN_AUDIT_SAMPLE_RATE", str(review_policy.get("human_audit_sample_rate", 0.10)))),
        review_policy=review_policy,
        translator_prompt=translator_prompt,
        quality_prompt=quality_prompt,
        output_dir=os.getenv("DEFAULT_OUTPUT_DIR", "outputs/persianization")
    )

    cfg.validate()
    return cfg
