"""Mel-spectrogram frontend matching Essentia's Discogs-EffNet input EXACTLY.

Contract (Phase 2 implements; tests/test_oracle_match.py judges):

    melspectrogram(audio16: np.ndarray) -> np.ndarray
        16 kHz mono float32 in, (n_spectrogram_frames, 96) log-mel out.
    patches(mel: np.ndarray, hop_frames: int) -> np.ndarray
        (n_patches, 128, 96) sliding windows; hop 62 = coarse, smaller = fine.

FIRST read the Essentia source for the exact melbands config + log
compression + patch layout, and record findings as comments here before
implementing. Parameter starting points and the verification protocol are in
PROJECT_PLAN.md ("Mel frontend parameters"). The oracle decides correctness;
do not lower its threshold.
"""
