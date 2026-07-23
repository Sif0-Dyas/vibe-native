"""Mel-spectrogram frontend matching Essentia's Discogs-EffNet input EXACTLY.

Contract (Phase 2 implements; tests/test_oracle_match.py judges):

    melspectrogram(audio16: np.ndarray) -> np.ndarray
        16 kHz mono float32 in, (n_spectrogram_frames, 96) log-mel out.
    patches(mel: np.ndarray, hop_frames: int) -> np.ndarray
        (n_patches, 128, 96) sliding windows; hop 62 = coarse, smaller = fine.

Phase-1 handoff (from the completed conversion session):
  * The embedder we ship is models/effnet.onnx = the zoo's discogs-effnet-BSDYNAMIC-1.
    Its tracked metadata models/discogs-effnet-bsdynamic-1.json is the AUTHORITATIVE
    input spec — read it BEFORE the Essentia source. It pins:
        input        serving_default_melspectrogram   shape [n, 128, 96]
        sample_rate  16000 ; algorithm TensorflowPredictEffnetDiscogs
        embeddings = output PartitionedCall:1 [n, 1280]
                     (PartitionedCall:0 [n, 400] is the head activations, unused)
    So the patch shape (128 frames x 96 mel bands) and sample rate are FIXED by the
    JSON. The exact mel filterbank (frameSize/hopSize/HTK mel scale/log compression)
    is NOT in the JSON — that still comes from the Essentia source, but it must
    produce the JSON's 128x96 patches.

PROCEDURE: read discogs-effnet-bsdynamic-1.json FIRST, then the Essentia source for
the melbands config + log compression + patch layout, and record findings as
comments here before implementing. Parameter starting points and the verification
protocol are in PROJECT_PLAN.md ("Mel frontend parameters"). The oracle decides
correctness; do not lower its threshold.
"""
