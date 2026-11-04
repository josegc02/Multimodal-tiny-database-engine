"""
Módulo de extracción de descriptores locales (SIFT, MFCC).
"""

from .image import SIFTExtractor
from .audio import MFCCExtractor

__all__ = ["SIFTExtractor", "MFCCExtractor"]