"""Audio evidence for the calling Agent; no automatic transcription engine."""

from .prepare import prepare_audio
from .evaluate import evaluate_audio_events

__all__ = ["prepare_audio", "evaluate_audio_events"]
