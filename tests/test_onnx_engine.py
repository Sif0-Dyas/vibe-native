"""onnx_engine's provider policy and session building, without onnxruntime.

CI has no onnxruntime (see test_import_safety.py), so these tests put a stub
``onnxruntime`` in sys.modules and import fresh copies of onnx_engine and tempo
against it. The stub records every InferenceSession built and the providers it
was handed; nothing here loads a model.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture()
def engine(monkeypatch, tmp_path):
    """Fresh (onnx_engine, tempo, sessions) bound to a stub onnxruntime.

    ``sessions`` collects (model file name, providers) per InferenceSession built.
    """
    sessions = []

    class FakeSession:
        def __init__(self, path, providers=None):
            sessions.append((Path(path).name, list(providers)))
            self._providers = list(providers)

        def get_providers(self):
            return self._providers

        def get_inputs(self):
            return [types.SimpleNamespace(name="in")]

        def get_outputs(self):
            return [types.SimpleNamespace(name="out")]

    ort = types.ModuleType("onnxruntime")
    ort.get_available_providers = lambda: ["DmlExecutionProvider", "CPUExecutionProvider"]
    ort.InferenceSession = FakeSession
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)

    # The stub-bound copies must not outlive this test: later tests that load the
    # real models would pick them up. Save the sys.modules entries and package
    # attributes by hand -- monkeypatch.delitem records nothing for an absent key.
    pkg = importlib.import_module("vibenative")
    names = ("onnx_engine", "tempo")
    saved = {n: (sys.modules.pop(f"vibenative.{n}", None), getattr(pkg, n, None)) for n in names}
    try:
        onnx_engine, tempo = (importlib.import_module(f"vibenative.{n}") for n in names)
        for f in ("effnet.onnx", "genre400.onnx", "tempocnn.onnx"):
            (tmp_path / f).write_bytes(b"")
        onnx_engine.MODELS = tempo.MODELS = tmp_path
        yield onnx_engine, tempo, sessions
    finally:
        for n, (mod, attr) in saved.items():
            if mod is None:
                sys.modules.pop(f"vibenative.{n}", None)
            else:
                sys.modules[f"vibenative.{n}"] = mod
            if attr is None:
                pkg.__dict__.pop(n, None)
            else:
                setattr(pkg, n, attr)


def test_tempo_and_genre_engine_share_provider_policy(engine, monkeypatch):
    # TempoCNN used to carry its own DML-first order and ignore VIBE_PROVIDER, so it
    # kept running on the GPU path that faults the NVIDIA driver after the genre
    # engine had moved to CPU. Both now resolve through onnx_engine.
    onnx_engine, tempo, sessions = engine
    dml_first = ["DmlExecutionProvider", "CPUExecutionProvider"]
    for env, expected in (
        ("", ["CPUExecutionProvider"]),
        ("gpu", dml_first),
        ("cpu", ["CPUExecutionProvider"]),
    ):
        monkeypatch.setenv("VIBE_PROVIDER", env)
        sessions.clear()
        tempo._engine.clear()
        onnx_engine._session(onnx_engine.MODELS / "genre400.onnx")
        tempo._session()
        assert sessions == [("genre400.onnx", expected), ("tempocnn.onnx", expected)], env
