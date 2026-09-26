"""
CrimeNet AI — Extraction Package Init
"""
from .fir_extractor       import extract as extract_fir
from .cdr_extractor       import extract as extract_cdr
from .financial_extractor import extract as extract_financial
from .social_extractor    import extract as extract_social
from .entity_resolver     import resolve
from .fusion_tagger       import tag

__all__ = [
    "extract_fir", "extract_cdr",
    "extract_financial", "extract_social",
    "resolve", "tag",
]
