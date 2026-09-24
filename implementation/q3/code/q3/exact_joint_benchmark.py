"""Contract for a future small exact Q3-C benchmark; no pseudo-result."""
from __future__ import annotations


def solve_exact_joint_small(*args, **kwargs):
    raise RuntimeError("exact Q3-C benchmark is a contract only until Q3-B is frozen")
