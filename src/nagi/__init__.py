"""Nagi — typed decisions with probability distributions."""

from nagi.api import Nagi, load_big, load_smol
from nagi.huge import NagiHuge, load_huge
from nagi.enormous import NagiEnormous, load_enormous, load_enormous_burst

__all__ = ["Nagi", "NagiHuge", "NagiEnormous", "load_smol", "load_big", "load_huge", "load_enormous", "load_enormous_burst"]
__version__ = "0.6.0"
