"""Nagi — typed decisions with probability distributions."""

from nagi.api import Nagi, load_big, load_smol
from nagi.huge import NagiHuge, load_huge

__all__ = ["Nagi", "NagiHuge", "load_smol", "load_big", "load_huge"]
__version__ = "0.4.0"
