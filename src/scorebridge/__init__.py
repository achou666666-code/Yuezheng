"""Compatibility package for the pre-0.4 ``scorebridge`` import path.

New code should import :mod:`yuezheng`.  The package path remains available so
existing Agents and projects can upgrade without changing their imports first.
"""

from pathlib import Path

from yuezheng import __all__, __brand__, __version__
from yuezheng import apply_review, create_review_packet, transcribe_score

# Let legacy imports such as ``scorebridge.audio`` resolve the canonical
# implementation without copying the package tree.
__path__ = [str(Path(__file__).resolve().parent.parent / "yuezheng")]

__all__ = ["create_review_packet", "apply_review", "transcribe_score"]
