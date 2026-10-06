"""
Four-Judge Blind Offense Evaluation Panel.
Judges evaluate candidate text blindly without seed, recipe, or target labels.
Implements strict consensus voting rules (>=3 votes, 2-2 tie handling, self-reported confidence tracking).
"""
from typing import Dict, Any, List, Optional, Tuple
from shared.api_client import AvalAIClient, AuthenticationError
from shared.rate_limiter import BudgetExceededError
from shared.circuit_breaker import CircuitBreakerTripped
from shared.schema_validator import validate_offense_judge_output, SchemaValidationError
from white_generation.config import WhiteGenerationConfig
from white_generation.storage import WhiteGenerationStorage


class BlindOffensePanel:
    def __init__(
        self,
        config: WhiteGenerationConfig,
        api_client: AvalAIClient,
        storage: WhiteGenerationStorage
    ):
        self.config = config
        self.client = api_client
        self.storage = storage
        self.policy = config.generation_policy.get("consensus_rules", {})

    def evaluate_candidate(
        self,
        candidate_id: str,
        candidate_text: str,
        candidate_context: Optional[str] = None,
        recipe: str = "ordinary"
    ) -> Dict[str, Any]:
        """
        Runs the 4 independent blinded LLM judges.
        """
        if not candidate_text:
            return {
                "consensus_status": "unresolved",
                "final_label": None,
                "final_status": "unresolved",
                "judge_votes": {},
                "flags": ["empty_text"],
                "reason": "Candidate text is empty"
            }

        user_content = f"متن برای ارزیابی:\n{candidate_text}"
        if candidate_context:
            user_content += f"\n\nزمینه:\n{candidate_context}"

        messages = [
            {"role": "system", "content": self.config.offense_judge_prompt},
            {"role": "user", "content": user_content}
        ]

        votes = {}
        flags = []

        # Query all 4 judges independently
        for idx, model in enumerate(self.config.judge_models, start=1):
            judge_key = f"judge_{idx}"
            try:
                res = self.client.invoke(
                    model=model,
                    messages=messages,
                    api_route=self.config.judge_route,
                    max_tokens=self.config.judge_max_tokens,
                    output_mode=self.config.judge_output_mode,
                    temperature=self.config.judge_temperature
                )

                parsed = res.get("parsed_json")
                raw_comp = res.get("raw_completion", "")

                val_err = None
                try:
                    val_data = validate_offense_judge_output(parsed, raw_completion=raw_comp)
                    label = val_data["label"]
                    confidence = val_data["confidence"]
                    reason = val_data["reason"]
                    flags_judge = val_data["flags"]
                    status_attempt = "success"
                except SchemaValidationError as sve:
                    val_err = str(sve)
                    label = None
                    confidence = None
                    reason = f"Schema validation error: {sve}"
                    flags_judge = ["schema_error"]
                    status_attempt = "failed"

                self.storage.record_attempt(
                    candidate_id=candidate_id,
                    step=judge_key,
                    model=model,
                    usage=res.get("usage", {}),
                    latency_sec=res.get("latency_sec", 0.0),
                    raw_completion=raw_comp,
                    parsed_json=parsed,
                    status=status_attempt,
                    error_message=val_err
                )

                votes[judge_key] = {
                    "model": model,
                    "label": label,
                    "confidence": confidence,
                    "self_reported_confidence": confidence,
                    "confidence_description": "اطمینان خوداظهاری مدل (فاقد کالیبراسیون آماری مستقل)",
                    "flags": flags_judge,
                    "reason": reason
                }

            except (AuthenticationError, BudgetExceededError, CircuitBreakerTripped):
                raise
            except Exception as e:
                self.storage.record_attempt(
                    candidate_id=candidate_id,
                    step=judge_key,
                    model=model,
                    usage={},
                    latency_sec=0.0,
                    raw_completion="",
                    parsed_json=None,
                    status="failed",
                    error_message=str(e)
                )
                votes[judge_key] = {
                    "model": model,
                    "label": None,
                    "confidence": None,
                    "self_reported_confidence": None,
                    "confidence_description": "اطمینان خوداظهاری مدل (فاقد کالیبراسیون آماری مستقل)",
                    "flags": ["judge_exception"],
                    "reason": str(e)
                }

        # Tabulate binary votes
        valid_labels = [v["label"] for v in votes.values() if v.get("label") in (0, 1)]
        zeros_count = sum(1 for l in valid_labels if l == 0)
        ones_count = sum(1 for l in valid_labels if l == 1)

        # Consensus Resolution Rules
        if len(valid_labels) < 4:
            consensus_status = "unresolved"
            final_label = None
            final_status = "unresolved"
            reason = f"Incomplete panel: only {len(valid_labels)}/4 valid votes obtained."
            flags.append("missing_judge_votes")

        elif zeros_count >= 3:
            consensus_status = "candidate0"
            final_label = 0
            # Check if 3/1 split or sensitive recipe requires review before acceptance
            hold_3_1 = self.policy.get("hold_split_3_1_for_review", True) and zeros_count == 3
            sensitive_recipes = set(self.policy.get("sensitive_recipes_requiring_review", []))
            is_sensitive = recipe in sensitive_recipes

            if hold_3_1 or is_sensitive:
                final_status = "review_queue"
                reason_tag = "Split 3-1 vote" if hold_3_1 else f"Sensitive recipe '{recipe}'"
                flags.append("split_3_1" if hold_3_1 else "sensitive_recipe")
                reason = f"Candidate clean ({zeros_count}-0s vs {ones_count}-1s) but held for human review ({reason_tag})."
            else:
                final_status = "accepted_white"
                reason = f"Unanimous consensus clean ({zeros_count}/4 clean votes)."

        elif ones_count >= 3:
            consensus_status = "candidate1"
            final_label = 1
            final_status = "rejected"
            flags.append("offense_detected")
            reason = f"Rejected: Panel classified as offensive ({ones_count}/4 offensive votes)."

        elif zeros_count == 2 and ones_count == 2:
            consensus_status = "tie_2_2"
            final_label = None
            final_status = "review_queue"
            flags.append("judge_tie_2_2")
            reason = "Tie split (2 votes clean vs 2 votes offensive). Held for Human-in-the-Loop review."

        else:
            consensus_status = "unresolved"
            final_label = None
            final_status = "unresolved"
            reason = "Panel unable to achieve resolution."

        return {
            "consensus_status": consensus_status,
            "final_label": final_label,
            "final_status": final_status,
            "judge_votes": votes,
            "flags": flags,
            "reason": reason
        }
