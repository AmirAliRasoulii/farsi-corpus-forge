"""
Realistic offline Mock LLM handler.
Simulates translation, refusal, fallback, quality checking, and blinded offense judging.
Used for deterministic offline verification and tests without consuming API credits.
"""
import re
import json
from typing import Dict, Any, List


def mock_llm_handler(
    model: str,
    messages: List[Dict[str, str]],
    extra_params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Simulates AvalAI responses deterministically based on user content and model.
    """
    sys_content = messages[0]["content"] if len(messages) > 0 and messages[0]["role"] == "system" else ""
    user_content = messages[-1]["content"] if len(messages) > 0 else ""

    # Simulated usage
    usage = {
        "prompt_tokens": len(user_content.split()) + 40,
        "completion_tokens": 35,
        "total_tokens": len(user_content.split()) + 75
    }

    # =========================================================================
    # 1. TRANSLATION ROLE (Project A)
    # =========================================================================
    if "دستورالعمل ترجمه وفادار پژوهشی" in sys_content or "English text to translate" in user_content:
        # Check for forced simulated refusal
        if "[SIMULATE_REFUSAL]" in user_content:
            data = {
                "status": "unable",
                "text_fa": None,
                "context_fa": None,
                "reason": "I cannot fulfill this request due to safety policies."
            }
            return {
                "raw_completion": json.dumps(data, ensure_ascii=False),
                "parsed_json": data,
                "usage": usage
            }

        # Check for forced primary model refusal to trigger fallback
        if "[FORCE_FALLBACK_ON_PRIMARY]" in user_content and "gpt-4o-mini" in model:
            data = {
                "status": "unable",
                "text_fa": None,
                "context_fa": None,
                "reason": "Primary model refused offensive content."
            }
            return {
                "raw_completion": json.dumps(data, ensure_ascii=False),
                "parsed_json": data,
                "usage": usage
            }

        # Specific translation cases
        if "Get out of here, you absolute idiot!" in user_content:
            data = {
                "status": "translated",
                "text_fa": "از اینجا گمشو بیرون، تو یک احمق تمام‌عیاری!",
                "context_fa": None,
                "reason": "ترجمه دقیق و عامیانه با حفظ کامل لحن توهین‌آمیز و شدت ناسزا"
            }
        elif "The conference will start tomorrow" in user_content:
            data = {
                "status": "translated",
                "text_fa": "کنفرانس فردا ساعت ۹ صبح در سالن اجتماعات اصلی آغاز خواهد شد.",
                "context_fa": None,
                "reason": "ترجمه رسمی و دقیق اطلاعیه دانشگاهی"
            }
        elif "I really cannot understand why the system failed" in user_content:
            data = {
                "status": "translated",
                "text_fa": "من واقعاً نمی‌توانم بفهمم که چرا سیستم تا این حد افتضاح شکست خورد.",
                "context_fa": None,
                "reason": "ترجمه دقیق با حفظ عبارت نمی‌توانم موجود در متن مبدأ"
            }
        elif "You must be kidding me, that is ridiculous!" in user_content:
            context_fa = "بحث درباره پیشنهاد بودجه" if "budget" in user_content.lower() else None
            data = {
                "status": "translated",
                "text_fa": "داری با من شوخی می‌کنی، این واقعاً مسخره‌ست!",
                "context_fa": context_fa,
                "reason": "ترجمه طبیعی اصطلاح عامیانه با حفظ کنایه"
            }
        elif "[SIMULATE_MALFORMED_JSON]" in user_content:
            return {
                "raw_completion": "Incomplete raw response {status: translated, text_fa: ...",
                "parsed_json": None,
                "usage": usage
            }
        elif "[SIMULATE_COVERT_CENSORSHIP]" in user_content:
            if "gpt-4o-mini" in model:
                data = {
                    "status": "translated",
                    "text_fa": "از اینجا تشریف ببرید فرد کم‌هوش [سانسور شده]",
                    "context_fa": None,
                    "reason": "تلطیف و جایگزینی ناسزا"
                }
            else:
                data = {
                    "status": "translated",
                    "text_fa": "از اینجا گمشو بیرون، تو احمق لعنتی!",
                    "context_fa": None,
                    "reason": "ترجمه وفادار عامیانه بدون سانسور"
                }
        elif "[SIMULATE_CENSORED]" in user_content:
            data = {
                "status": "translated",
                "text_fa": "لطفاً از اینجا تشریف ببرید فرد کم‌هوش [سانسور شده]",
                "context_fa": None,
                "reason": "تلطیف و جایگزینی ناسزا"
            }
        else:
            # General fallback translation
            data = {
                "status": "translated",
                "text_fa": f"ترجمه روان فارسی برای: {user_content[:60]}",
                "context_fa": "زمینه ترجمه شده" if "Context:" in user_content else None,
                "reason": "ترجمه استاندارد فارسی"
            }

        return {
            "raw_completion": json.dumps(data, ensure_ascii=False),
            "parsed_json": data,
            "usage": usage
        }

    # =========================================================================
    # 2. TRANSLATION QUALITY EVALUATION (Project A)
    # =========================================================================
    if "دستورالعمل کنترل کیفیت و وفاداری ترجمه" in sys_content or "English original:" in user_content:
        has_ctx = "English context:" in user_content
        # Check simulated cases
        if "[SIMULATE_SEVERITY_SHIFT]" in user_content:
            data = {
                "fluency": 5,
                "naturalness": 5,
                "register_match": 3,
                "cultural_fit": 3,
                "semantic_fidelity": 3,
                "severity_fidelity": 2,
                "context_fidelity": {"applicable": has_ctx, "score": 5 if has_ctx else None},
                "target_preserved": True,
                "stance_preserved": True,
                "negation_preserved": True,
                "quotation_preserved": True,
                "ambiguity_preserved": True,
                "flags": ["severity_changed"],
                "reason": "شدت ناسزا به طور ناموجه تلطیف شده است."
            }
        elif "[SIMULATE_JUDGE_DISAGREEMENT]" in user_content:
            if "command" in model or "claude" in model or "sonnet" in model or "deepseek" not in model:
                # Judge 2 flags censorship
                data = {
                    "fluency": 3,
                    "naturalness": 3,
                    "register_match": 2,
                    "cultural_fit": 2,
                    "semantic_fidelity": 2,
                    "severity_fidelity": 1,
                    "context_fidelity": {"applicable": has_ctx, "score": 2 if has_ctx else None},
                    "target_preserved": True,
                    "stance_preserved": False,
                    "negation_preserved": True,
                    "quotation_preserved": True,
                    "ambiguity_preserved": True,
                    "flags": ["censored_content"],
                    "reason": "داور دوم سانسور پنهان را تشخیص داد."
                }
            else:
                # Judge 1 passes
                data = {
                    "fluency": 5,
                    "naturalness": 5,
                    "register_match": 5,
                    "cultural_fit": 5,
                    "semantic_fidelity": 5,
                    "severity_fidelity": 5,
                    "context_fidelity": {"applicable": has_ctx, "score": 5 if has_ctx else None},
                    "target_preserved": True,
                    "stance_preserved": True,
                    "negation_preserved": True,
                    "quotation_preserved": True,
                    "ambiguity_preserved": True,
                    "flags": [],
                    "reason": "داور اول ترجمه را بدون اشکال ارزیابی کرد."
                }

        elif "[سانسور شده]" in user_content or "کم‌هوش" in user_content:
            data = {
                "fluency": 3,
                "naturalness": 2,
                "register_match": 1,
                "cultural_fit": 2,
                "semantic_fidelity": 2,
                "severity_fidelity": 1,
                "context_fidelity": {"applicable": has_ctx, "score": 2 if has_ctx else None},
                "target_preserved": True,
                "stance_preserved": False,
                "negation_preserved": True,
                "quotation_preserved": True,
                "ambiguity_preserved": True,
                "flags": ["censored_content", "severity_changed"],
                "reason": "ناسزا تلطیف و سانسور شده است."
            }
        else:
            data = {
                "fluency": 5,
                "naturalness": 5,
                "register_match": 5,
                "cultural_fit": 5,
                "semantic_fidelity": 5,
                "severity_fidelity": 5,
                "context_fidelity": {"applicable": has_ctx, "score": 5 if has_ctx else None},
                "target_preserved": True,
                "stance_preserved": True,
                "negation_preserved": True,
                "quotation_preserved": True,
                "ambiguity_preserved": True,
                "flags": [],
                "reason": "ترجمه روان، طبیعی و وفادار بدون هیچ‌گونه سانسور یا انحراف معنایی."
            }

        return {
            "raw_completion": json.dumps(data, ensure_ascii=False),
            "parsed_json": data,
            "usage": usage
        }


    # =========================================================================
    # 3. WHITE GENERATION RECIPES (Project B)
    # =========================================================================
    if "تولید داده سالم" in sys_content or "متن بذر:" in user_content:
        if "minimal_disambiguation" in user_content or "رفع ابهام" in user_content:
            cand = "رفتار دیروز شما نیاز به هماهنگی بیشتری داشت و انتظار عملکرد بهتری می‌رفت."
        elif "criticism" in user_content or "نقد مستدل" in user_content:
            cand = "تصمیمات مدیریتی شما در این بخش فاقد کارایی لازم و برنامه‌ریزی دقیق است."
        elif "hard_negative" in user_content or "هارد نگاتیو" in user_content:
            cand = "این ادعا که انتقاد مساوی با نفرت‌پراکنی است یک مغالطه آشکار است و من به شدت با آن مخالفم."
        elif "educational" in user_content:
            cand = "تحلیل پدیده‌های ارتباطی نشان می‌دهد که تفکیک نقد ساختاری از تخریب شخصی اهمیت حیاتی دارد."
        elif "reported_condemnation" in user_content:
            cand = "گزارش‌ها حاکی از آن است که اهانت‌های مطرح‌شده در جلسه اخیر توسط کمیته انضباطی محکوم شد."
        else:
            cand = "برای بهبود کیفیت کار گروهی، بررسی ساختار فرآیندها پیشنهاد می‌شود."

        data = {
            "status": "generated",
            "candidate_text": cand,
            "candidate_context": None,
            "reason": "تولید کاندیدای سالم متناسب با دستورالعمل"
        }
        return {
            "raw_completion": json.dumps(data, ensure_ascii=False),
            "parsed_json": data,
            "usage": usage
        }

    # =========================================================================
    # 4. WHITE GENERATION QUALITY JUDGE (Project B)
    # =========================================================================
    if "ارزیابی کیفیت فارسی کاندیدای داده سالم" in sys_content or "متن کاندیدای فارسی:" in user_content:
        data = {
            "fluency": 5,
            "naturalness": 5,
            "conversion_success": 5,
            "is_persian": True,
            "flags": [],
            "reason": "متن کاملاً سلیس و طبیعی فارسی"
        }
        return {
            "raw_completion": json.dumps(data, ensure_ascii=False),
            "parsed_json": data,
            "usage": usage
        }

    # =========================================================================
    # 5. BLINDED 4-JUDGE OFFENSE PANEL (Project B)
    # =========================================================================
    if "داوری بی‌طرف توهین" in sys_content or "متن برای ارزیابی:" in user_content:
        # Check if the evaluated text is offensive
        is_offensive = any(word in user_content for word in ["احمق", "گمشو", "بیشعور", "عوضی", "idiot"])
        
        # Check for simulated 2-2 tie
        if "[SIMULATE_TIE_2_2]" in user_content:
            lbl = 1 if ("gpt" in model.lower() or "gemini" in model.lower() or "1" in model or "3" in model) else 0
        elif "[SIMULATE_SPLIT_3_1]" in user_content:
            lbl = 1 if ("deepseek" in model.lower() or model == "judge_4") else 0
        else:
            lbl = 1 if is_offensive else 0

        data = {
            "label": lbl,
            "confidence": 0.95,
            "reason": "متن دارای توهین و الفاظ رکیک است" if lbl == 1 else "متن کاملاً سالم، محترمانه و غیرتوهین‌آمیز است"
        }
        return {
            "raw_completion": json.dumps(data, ensure_ascii=False),
            "parsed_json": data,
            "usage": usage
        }

    # Fallback generic JSON
    generic = {"status": "success", "text": "OK"}
    return {
        "raw_completion": json.dumps(generic, ensure_ascii=False),
        "parsed_json": generic,
        "usage": usage
    }
