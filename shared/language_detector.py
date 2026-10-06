"""
Accurate language routing and script detection for Persian, English, Mixed, and Fingilish.
Pure Python - zero heavy external model dependencies.
"""
import re
from typing import Dict, Any, Optional

# Regex for Arabic/Persian scripts
PERSIAN_CHARS_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
PERSIAN_SPECIFIC_CHARS_RE = re.compile(r'[گچپژ]')
LATIN_CHARS_RE = re.compile(r'[a-zA-Z]')

# Common Fingilish tokens and prefixes/suffixes
FINGILISH_KEYWORDS = {
    'salam', 'chetori', 'chetori?', 'chetore', 'khoob', 'khoobi', 'chera', 'are', 'na', 'bale',
    'kheili', 'man', 'to', 'oo', 'ma', 'shoma', 'anha', 'inha', 'in', 'an',
    'ke', 'ro', 'ba', 'baraye', 'az', 'dar', 'ta', 'vali', 'ama', 'chon',
    'nemidonam', 'nemidoonam', 'nemikham', 'nemikham?', 'mikhaham', 'mikham',
    'fekr', 'mikonam', 'mikoni', 'kard', 'kardan', 'shod', 'shodan', 'hast',
    'hastam', 'hasti', 'hastim', 'nist', 'nistam', 'nisti', 'daghighan',
    'damet', 'garm', 'aslan', 'vaghedan', 'behet', 'behesh', 'behem', 'pesare',
    'dokhtare', 'khahar', 'baradar', 'madar', 'pedar', 'agha', 'khanom', 'khoobe',
    'dadash', 'abji', 'halet', 'hale', 'haletoon', 'emrooz', 'farda', 'dirooz',
    'nemiam', 'miam', 'raftam', 'sar', 'kar', 'azizam', 'fadat', 'delam', 'tange'
}

FINGILISH_PATTERNS = [
    re.compile(r'\b(mikh|nemikh|mikon|nemikon|midoon|nemidon|nemiam|miam)[a-z]*\b', re.IGNORECASE),
    re.compile(r'\b(kheili|khoob[ie]?|damet|garm|vaghedan|dadash|halet)\b', re.IGNORECASE),
    re.compile(r'\b[a-z]+(am|et|esh|emoon|etoon|eshoon)\b', re.IGNORECASE),
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
    
    # If declared language is given and valid
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
        # Only punctuation, digits, or emojis
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

    # Check for Fingilish if mostly Latin characters
    if en_ratio >= 0.7:
        words = re.findall(r'[a-zA-Z]+', raw.lower())
        fingilish_matches = sum(1 for w in words if w in FINGILISH_KEYWORDS)
        pattern_matches = sum(1 for p in FINGILISH_PATTERNS if p.search(raw))
        
        if (len(words) > 0 and (fingilish_matches / len(words) >= 0.25 or fingilish_matches >= 2 or pattern_matches >= 2)):
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

    # If both Persian and English characters are present
    if fa_chars > 0 and en_chars > 0:
        flags.append("mixed_script")
        # If Persian characters are present and substantial (e.g. >= 40% or Persian words dominant)
        if fa_ratio >= 0.4:
            # Persian with some English terms (e.g. "در توییتر tweet زدم")
            # Must remain Persian, NOT translated to Persian!
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
            # English with a few Persian characters
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

    # Pure Persian script
    if fa_chars > 0 and en_chars == 0:
        return {
            "lang": "fa",
            "origin_status": "native_fa",
            "is_uncertain": False,
            "fa_char_count": fa_chars,
            "en_char_count": 0,
            "fa_ratio": 1.0,
            "en_ratio": 0.0,
            "flags": ["pure_persian_script"],
            "reason": "Pure Persian/Arabic script"
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
