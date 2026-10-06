"""
Accurate language routing and script detection for Persian, English, Mixed, and Fingilish.
Pure Python - zero heavy external model dependencies.
"""
import re
from typing import Dict, Any, Optional

# Regex for Arabic/Persian scripts
PERSIAN_CHARS_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
PERSIAN_SPECIFIC_CHARS_RE = re.compile(r'[گچپژ]')
# Characters strictly exclusive to Arabic orthography that are not standard Persian
ARABIC_EXCLUSIVE_CHARS_RE = re.compile(r'[\u0629\u064A\u0643\u0649\u0671]')
# Common Persian function words and pronouns that indicate Persian language
PERSIAN_COMMON_WORDS_RE = re.compile(
    r'(?:^|\s|[«"\'\(\[])(من|تو|او|ما|شما|آنها|این|آن|با|برای|که|را|است|شد|شده|شدن|کرد|کرده|کردن|بود|یک|هم|اما|ولی|اگر|چون|نیست|هست|موافق|دارد|دارم|داری|دارند|رفت|گفت)(?:$|\s|[»"\'\)\].،؛؟!])',
    re.UNICODE
)
LATIN_CHARS_RE = re.compile(r'[a-zA-Z]')

# UNAMBIGUOUS Fingilish keywords - words that virtually NEVER appear in standard English texts
UNAMBIGUOUS_FINGILISH_KEYWORDS = {
    'salam', 'chetori', 'chetore', 'khoobi', 'kheili', 'chera', 'bale',
    'shoma', 'anha', 'inha', 'baraye', 'chon',
    'nemidonam', 'nemidoonam', 'nemikham', 'mikhaham', 'mikham',
    'mikonam', 'mikoni', 'kardan', 'shodan', 'hastam', 'hastim',
    'nistam', 'nisti', 'daghighan', 'damet', 'garm', 'aslan', 'vaghedan',
    'behet', 'behesh', 'behem', 'pesare', 'dokhtare', 'khahar', 'baradar',
    'madar', 'pedar', 'agha', 'khanom', 'khoobe', 'dadash', 'abji',
    'halet', 'hale', 'haletoon', 'emrooz', 'farda', 'dirooz', 'nemiam',
    'miam', 'raftam', 'azizam', 'fadat', 'delam', 'ghorbanat', 'dorood',
    'mamnoon', 'dastet', 'khoshbakhtam', 'befarmaeed', 'bebin', 'baba'
}

# Ambiguous tokens that exist in English (e.g. 'are' = are/yes, 'to' = to/you, 'an' = an/that, 'in' = in/this)
# These MUST NOT trigger Fingilish unless accompanied by strong unambiguous Fingilish words!
AMBIGUOUS_SHARED_TOKENS = {'are', 'to', 'an', 'in', 'man', 'na', 'ma', 'ke', 'ro', 'ba', 'az', 'dar', 'ta', 'vali', 'ama', 'so', 'as', 'no', 'bad'}

# Strict Fingilish morphological verb patterns
FINGILISH_VERB_PATTERNS = [
    re.compile(r'\b(nemikh|mikh|nemikon|mikon|nemidoon|midoon|nemidon|midon|nemiam|miam)(am|i|ad|e|im|id|an|and)?\b', re.IGNORECASE),
    re.compile(r'\b(raft|omad|goft|kard|shod)(am|i|e|im|id|an|and)\b', re.IGNORECASE),
    re.compile(r'\b(kheili|khoob[ie]|damet|vaghedan|dadash|azizam)\b', re.IGNORECASE),
]


def detect_language(text: Optional[str], declared_language: Optional[str] = None) -> Dict[str, Any]:
    """
    Detects language of a text string with fine-grained status.
    
    Returns a dict with:
      - lang: 'fa' | 'en' | 'mixed' | 'fingilish' | 'unknown'
      - origin_status: 'native_fa' | 'needs_translation_en_to_fa' | 'uncertain' | 'fingilish'
      - is_uncertain: bool
      - fa_char_count: int
      - en_char_count: int
      - fa_ratio: float
      - en_ratio: float
      - flags: list of str
      - reason: str
    """
    if text is None or not str(text).strip():
        return {
            "lang": "unknown",
            "origin_status": "uncertain",
            "is_uncertain": True,
            "fa_char_count": 0,
            "en_char_count": 0,
            "fa_ratio": 0.0,
            "en_ratio": 0.0,
            "flags": ["empty_text"],
            "reason": "Text is empty or whitespace"
        }

    raw = str(text)
    
    # Normalize declared language
    norm_decl = str(declared_language).strip().lower() if declared_language else ""
    if norm_decl in ("fa", "per", "fas", "persian", "fa-ir"):
        declared_lang = "fa"
    elif norm_decl in ("en", "eng", "english", "en-us", "en-gb"):
        declared_lang = "en"
    else:
        declared_lang = None

    # Count script characters
    fa_chars = len(PERSIAN_CHARS_RE.findall(raw))
    en_chars = len(LATIN_CHARS_RE.findall(raw))
    total_letters = fa_chars + en_chars

    flags = []

    if total_letters == 0:
        flags.append("no_alphabetical_chars")
        if declared_lang:
            return {
                "lang": declared_lang,
                "origin_status": "native_fa" if declared_lang == "fa" else "needs_translation_en_to_fa",
                "is_uncertain": False,
                "fa_char_count": 0,
                "en_char_count": 0,
                "fa_ratio": 0.0,
                "en_ratio": 0.0,
                "flags": flags,
                "reason": f"No letters found; relied on declared language '{declared_lang}'"
            }
        return {
            "lang": "unknown",
            "origin_status": "uncertain",
            "is_uncertain": True,
            "fa_char_count": 0,
            "en_char_count": 0,
            "fa_ratio": 0.0,
            "en_ratio": 0.0,
            "flags": flags,
            "reason": "No Persian or Latin alphabet characters found"
        }

    fa_ratio = fa_chars / total_letters
    en_ratio = en_chars / total_letters

    # Check for script vs declared language conflict
    if declared_lang == "en" and fa_ratio >= 0.7:
        flags.append("language_script_conflict")
        flags.append("declared_en_but_persian_script")
        return {
            "lang": "fa",
            "origin_status": "uncertain",
            "is_uncertain": True,
            "fa_char_count": fa_chars,
            "en_char_count": en_chars,
            "fa_ratio": fa_ratio,
            "en_ratio": en_ratio,
            "flags": flags,
            "reason": "Declared language is 'en' but text is written in Persian/Arabic script."
        }

    if declared_lang == "fa" and en_ratio >= 0.7:
        flags.append("language_script_conflict")
        flags.append("declared_fa_but_latin_script")
        return {
            "lang": "fingilish" if en_ratio >= 0.7 else "uncertain",
            "origin_status": "uncertain",
            "is_uncertain": True,
            "fa_char_count": fa_chars,
            "en_char_count": en_chars,
            "fa_ratio": fa_ratio,
            "en_ratio": en_ratio,
            "flags": flags,
            "reason": "Declared language is 'fa' but text is written in Latin script."
        }

    # Fingilish check (only when Latin characters dominate)
    if en_ratio >= 0.7:
        words = [w.lower() for w in re.findall(r'[a-zA-Z]+', raw)]
        unambig_matches = sum(1 for w in words if w in UNAMBIGUOUS_FINGILISH_KEYWORDS)
        pattern_matches = sum(1 for p in FINGILISH_VERB_PATTERNS if p.search(raw))
        ambig_matches = sum(1 for w in words if w in AMBIGUOUS_SHARED_TOKENS)

        # Stricter Fingilish criteria:
        # If declared_lang == 'en', do NOT classify as Fingilish unless overwhelming unambiguous proof
        is_fingilish = False
        if declared_lang == "en":
            # For declared English, require at least 3 unambiguous keywords or 2 patterns + 1 unambiguous keyword
            if unambig_matches >= 3 or (unambig_matches >= 1 and pattern_matches >= 2):
                is_fingilish = True
        else:
            # When undeclared, require at least 2 unambiguous keywords or 1 unambiguous keyword + 1 pattern
            if unambig_matches >= 2 or (unambig_matches >= 1 and pattern_matches >= 1):
                is_fingilish = True
            elif pattern_matches >= 2 and ambig_matches >= 1:
                is_fingilish = True

        if is_fingilish:
            flags.append("fingilish_detected")
            return {
                "lang": "fingilish",
                "origin_status": "fingilish",
                "is_uncertain": True,
                "fa_char_count": fa_chars,
                "en_char_count": en_chars,
                "fa_ratio": fa_ratio,
                "en_ratio": en_ratio,
                "flags": flags,
                "reason": "Text appears to be Fingilish (Persian in Latin script)"
            }

    # If both Persian and English characters are present (Mixed Script)
    if fa_chars > 0 and en_chars > 0:
        flags.append("mixed_script")
        if fa_ratio >= 0.4:
            # Persian dominant with loanwords (e.g. "در توییتر tweet زدم")
            if declared_lang == "fa" or fa_ratio >= 0.6:
                flags.append("persian_dominant")
                return {
                    "lang": "fa",
                    "origin_status": "native_fa",
                    "is_uncertain": False,
                    "fa_char_count": fa_chars,
                    "en_char_count": en_chars,
                    "fa_ratio": fa_ratio,
                    "en_ratio": en_ratio,
                    "flags": flags,
                    "reason": "Persian dominant text with embedded Latin/English loanwords"
                }
            else:
                flags.append("mixed_uncertain")
                return {
                    "lang": "mixed",
                    "origin_status": "uncertain",
                    "is_uncertain": True,
                    "fa_char_count": fa_chars,
                    "en_char_count": en_chars,
                    "fa_ratio": fa_ratio,
                    "en_ratio": en_ratio,
                    "flags": flags,
                    "reason": "Mixed Persian and English text requiring explicit review"
                }
        else:
            if declared_lang == "en" or en_ratio >= 0.8:
                return {
                    "lang": "en",
                    "origin_status": "needs_translation_en_to_fa",
                    "is_uncertain": False,
                    "fa_char_count": fa_chars,
                    "en_char_count": en_chars,
                    "fa_ratio": fa_ratio,
                    "en_ratio": en_ratio,
                    "flags": flags,
                    "reason": "English dominant text with minimal Persian characters"
                }
            else:
                return {
                    "lang": "mixed",
                    "origin_status": "uncertain",
                    "is_uncertain": True,
                    "fa_char_count": fa_chars,
                    "en_char_count": en_chars,
                    "fa_ratio": fa_ratio,
                    "en_ratio": en_ratio,
                    "flags": flags,
                    "reason": "Mixed script with unclear language dominance"
                }

    # Arabic script evaluation (Persian vs Arabic)
    if fa_chars > 0 and en_chars == 0:
        has_persian_specific = bool(PERSIAN_SPECIFIC_CHARS_RE.search(raw))
        has_persian_common_words = bool(PERSIAN_COMMON_WORDS_RE.search(raw))
        has_arabic_exclusive = bool(ARABIC_EXCLUSIVE_CHARS_RE.search(raw))

        if has_arabic_exclusive and not (has_persian_specific or has_persian_common_words):
            flags.append("arabic_script_detected")
            if declared_lang == "fa":
                # User declared Persian despite Arabic characters (e.g. loan phrases or religious idioms)
                return {
                    "lang": "fa",
                    "origin_status": "native_fa",
                    "is_uncertain": False,
                    "fa_char_count": fa_chars,
                    "en_char_count": 0,
                    "fa_ratio": 1.0,
                    "en_ratio": 0.0,
                    "flags": flags,
                    "reason": "Arabic orthographic features detected in declared Persian text"
                }
            else:
                return {
                    "lang": "ar",
                    "origin_status": "uncertain",
                    "is_uncertain": True,
                    "fa_char_count": fa_chars,
                    "en_char_count": 0,
                    "fa_ratio": 1.0,
                    "en_ratio": 0.0,
                    "flags": flags,
                    "reason": "Arabic orthography detected (not verified Persian)"
                }

        flags.append("pure_persian_script")
        return {
            "lang": "fa",
            "origin_status": "native_fa",
            "is_uncertain": False,
            "fa_char_count": fa_chars,
            "en_char_count": 0,
            "fa_ratio": 1.0,
            "en_ratio": 0.0,
            "flags": flags,
            "reason": "Pure Persian script"
        }

    # Pure Latin script
    if en_chars > 0 and fa_chars == 0:
        return {
            "lang": "en",
            "origin_status": "needs_translation_en_to_fa",
            "is_uncertain": False,
            "fa_char_count": 0,
            "en_char_count": en_chars,
            "fa_ratio": 0.0,
            "en_ratio": 1.0,
            "flags": ["pure_latin_script"],
            "reason": "Pure Latin/English script"
        }

    return {
        "lang": "unknown",
        "origin_status": "uncertain",
        "is_uncertain": True,
        "fa_char_count": fa_chars,
        "en_char_count": en_chars,
        "fa_ratio": fa_ratio,
        "en_ratio": en_ratio,
        "flags": ["unrecognized_script"],
        "reason": "Unrecognized script composition"
    }
