"""Nagi — typed decisions with probability distributions.

The model lines (``Nagi``, ``load_smol`` ... ``load_enormous_burst``) import torch; they load on first access, so
``import nagi.burst2`` (Burst V2, numpy only) does not import torch.
"""

_LAZY = {"Nagi": "nagi.api", "load_big": "nagi.api", "load_smol": "nagi.api",
         "NagiHuge": "nagi.huge", "load_huge": "nagi.huge",
         "NagiEnormous": "nagi.enormous", "load_enormous": "nagi.enormous", "load_enormous_burst": "nagi.enormous"}

__all__ = ["Nagi", "NagiHuge", "NagiEnormous", "load_smol", "load_big", "load_huge", "load_enormous", "load_enormous_burst"]
__version__ = "0.6.0"


def __getattr__(name):
    if name in _LAZY:
        import importlib

        value = getattr(importlib.import_module(_LAZY[name]), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'nagi' has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_LAZY))
