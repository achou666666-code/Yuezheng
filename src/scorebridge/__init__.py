"""ScoreBridge: an Agent-facing bridge for editable music scores."""
__version__ = "0.3.0"
from .review import create_review_packet, apply_review
from .workflow import transcribe_score

__all__ = ["create_review_packet", "apply_review", "transcribe_score"]
