"""Yuezheng: an Agent-facing assistant for editable music projects."""
from importlib.metadata import PackageNotFoundError, version

__brand__ = "Yuezheng"
try:
    __version__ = version("yuezheng")
except PackageNotFoundError:
    # Source checkouts without an installed distribution still remain importable.
    __version__ = "0+unknown"
from .review import create_review_packet, apply_review
from .workflow import transcribe_score

__all__ = ["create_review_packet", "apply_review", "transcribe_score"]
