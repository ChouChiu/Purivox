from pathlib import Path

import numpy as np
import soundfile as sf

from features.neural_separation.catalog import DEFAULT_MODEL_ID, get_model, model_catalog
from features.neural_separation.inference import MdxNetSpec, demix_chunks
from features.neural_separation.models import NeuralJob
from features.neural_separation.processing import run_neural_job
from shared.audio import HI_RES_SAMPLE_RATE, create_pcm_audio
from shared.processing import CancellationToken


def test_catalog_is_unique_and_has_hashes():
    catalog = model_catalog()
    assert get_model(DEFAULT_MODEL_ID) in catalog
    assert len({entry.id for entry in catalog}) == len(catalog)
    assert all(len(entry.sha256) == 64 for entry in catalog)


def test_demix_identity_handles_multiple_chunks():
    spec = MdxNetSpec(n_fft=32, dim_f=12, dim_t=9, hop=8, segment_size=9)
    rng = np.random.default_rng(7)
    mix = rng.normal(0, 0.1, (2, 333)).astype(np.float32)
    calls = []
    output = demix_chunks(
        mix,
        spec,
        lambda chunk: chunk,
        CancellationToken(),
        lambda current, total: calls.append((current, total)),
    )
    assert output.shape == mix.shape
    assert np.max(np.abs(output - mix)) < 1e-6
    assert calls and calls[-1][0] == calls[-1][1]


def test_demix_identity_writes_supplied_disk_buffer():
    spec = MdxNetSpec(n_fft=32, dim_f=12, dim_t=9, hop=8, segment_size=9)
    mix = np.random.default_rng(9).normal(0, 0.1, (2, 173)).astype(np.float32)
    target = create_pcm_audio(2, mix.shape[1], spec.sample_rate)
    try:
        output = demix_chunks(
            mix,
            spec,
            lambda chunk: chunk,
            CancellationToken(),
            output=target.samples,
        )
        assert output is target.samples
        assert np.max(np.abs(output - mix)) < 1e-6
    finally:
        target.cleanup()


def test_neural_job_writes_hi_res_outputs(monkeypatch, tmp_path: Path):
    sample_rate = 8_000
    time = np.arange(sample_rate) / sample_rate
    input_path = tmp_path / "input.wav"
    sf.write(input_path, 0.2 * np.sin(2 * np.pi * 220 * time), sample_rate)

    class IdentityNetwork:
        def __init__(self, _path: Path):
            pass

        def separate(self, mix, _token, progress, output):
            output[:] = mix
            progress(1, 1)
            return output

    monkeypatch.setattr(
        "features.neural_separation.processing.ensure_model",
        lambda *_args: tmp_path / "model.onnx",
    )
    monkeypatch.setattr("features.neural_separation.processing.MdxNet", IdentityNetwork)

    result = run_neural_job(NeuralJob(input_path, tmp_path), CancellationToken())

    assert len(result.outputs) == 2
    for output in result.outputs:
        info = sf.info(output)
        assert info.samplerate == HI_RES_SAMPLE_RATE
        assert info.frames == HI_RES_SAMPLE_RATE
        assert info.channels == 2
        assert info.subtype == "PCM_24"
