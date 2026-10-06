"""
Independent Persian quality judge for white candidates.
Validates naturalness, grammatical fluency, and conversion success.
"""
from typing import Dict, Any, Optional
from shared.api_client import AvalAIClient, AuthenticationError
from shared.rate_limiter import BudgetExceededError
from shared.circuit_breaker import CircuitBreakerTripped
from white_generation.config import WhiteGenerationConfig
from white_generation.storage import WhiteGenerationStorage


class WhiteQualityJudge:
    def __init__(
        self,
        config: WhiteGenerationConfig,
        api_client: AvalAIClient,
        storage: WhiteGenerationStorage
    ):
        self.config = config
        self.client = api_client
        self.storage = storage
        self.min_score = config.generation_policy.get("min_persian_quality_score", 4)

    def evaluate_candidate_quality(
        self,
        candidate_id: str,
        candidate_text: str,
        candidate_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates Persian fluency and coherence of candidate.
        """
        if not candidate_text:
            return {
                "quality_status": "rejected",
                "persian_quality_score": 1,
                "flags": ["empty_candidate_text"],
                "reason": "Candidate text is empty"
            }

        user_content = f"متن کاندیدای فارسی:\n{candidate_text}"
        if candidate_context:
            user_content += f"\n\nزمینه:\n{candidate_context}"

        messages = [
            {"role": "system", "content": self.config.quality_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            res = self.client.invoke(
                model=self.config.quality_model,
                messages=messages,
                api_route=self.config.quality_route,
                max_tokens=self.config.quality_max_tokens,
                output_mode=self.config.quality_output_mode,
                temperature=self.config.quality_temperature,
                extra_params=self.config.quality_extra_json
            )

            parsed = res.get("parsed_json")
            raw_comp = res.get("raw_completion", "")

            self.storage.record_attempt(
                candidate_id=candidate_id,
                step="white_quality_eval",
                model=self.config.quality_model,
                usage=res.get("usage", {}),
                latency_sec=res.get("latency_sec", 0.0),
                raw_completion=raw_comp,
                parsed_json=parsed,
                status="success" if parsed else "failed",
                error_message=None if parsed else "QC JSON parse failure"
            )

            if not parsed or not isinstance(parsed, dict):
                return {
                    "quality_status": "review_required",
                    "persian_quality_score": 1,
                    "flags": ["qc_parse_error"],
                    "reason": "Failed to parse quality evaluation response"
                }

            scores = []
            for dim in ("fluency", "naturalness", "conversion_success"):
                val = parsed.get(dim)
                if isinstance(val, bool) or not isinstance(val, int) or val < 1 or val > 5:
                    scores.append(1)
                else:
                    scores.append(val)

            avg_score = sum(scores) / len(scores)
            raw_flags = parsed.get("flags") or []
            flags = [str(f) for f in raw_flags] if isinstance(raw_flags, list) else []
            is_persian = parsed.get("is_persian", True)
            if not isinstance(is_persian, bool):
                is_persian = True

            if avg_score >= self.min_score and is_persian:
                status = "accepted"
            else:
                status = "rejected" if avg_score < 2.5 else "review_required"

            return {
                "quality_status": status,
                "persian_quality_score": round(avg_score, 2),
                "flags": flags,
                "reason": str(parsed.get("reason", ""))
            }

        except (AuthenticationError, BudgetExceededError, CircuitBreakerTripped):
            raise
        except Exception as e:
            self.storage.record_attempt(
                candidate_id=candidate_id,
                step="white_quality_eval",
                model=self.config.quality_model,
                usage={},
                latency_sec=0.0,
                raw_completion="",
                parsed_json=None,
                status="failed",
                error_message=str(e)
            )
            return {
                "quality_status": "review_required",
                "persian_quality_score": 1,
                "flags": ["qc_exception"],
                "reason": str(e)
            }
