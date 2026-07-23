"""Musical key via chroma-profile correlation. Contract (Phase 3):

    estimate(audio: np.ndarray, sr: int) -> (key: str, scale: str, strength: float)

Correlate the track-level chroma vector against the same 24 major/minor
profiles Essentia's KeyExtractor uses (check its default profile set).
Acceptance vs oracle: exact match >= 90%; log every disagreement.
"""
