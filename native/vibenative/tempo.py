"""BPM via TempoCNN (ONNX). Contract (Phase 3):

    estimate(audio: np.ndarray, sr: int) -> (bpm: float, confidence: float)

Acceptance vs oracle: within 2% OR a half/double multiple for >= 95% of
tracks. The app's UI already renders the octave ambiguity ("87.0/174.0?").
"""
