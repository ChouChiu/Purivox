"""The browser shell speaks JSON; these lock the shape it speaks."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from web import bridge, limits


def _write(path: Path, samples: np.ndarray, sample_rate: int) -> Path:
    sf.write(path, samples, sample_rate)
    return path


@pytest.fixture
def reference_scene(tmp_path: Path):
    sample_rate = 8_000
    time = np.arange(sample_rate * 3) / sample_rate
    accompaniment = 0.4 * np.sin(2 * np.pi * 110 * time)
    vocal = 0.3 * np.sin(2 * np.pi * 440 * time)
    stereo = np.stack([accompaniment, accompaniment], axis=1).astype(np.float32)
    mix = np.stack([accompaniment + vocal] * 2, axis=1).astype(np.float32)
    return (
        _write(tmp_path / "song.wav", mix, sample_rate),
        _write(tmp_path / "acc.wav", stereo, sample_rate),
        tmp_path / "out.wav",
    )


def test_run_reference_returns_outputs_and_json_progress(reference_scene):
    song, accompaniment, output = reference_scene
    updates: list[str] = []

    payload = bridge.run_reference(
        json.dumps(
            {
                "song": str(song),
                "accompaniment": str(accompaniment),
                "output": str(output),
                "strength": 75,
                "sigma": 3,
                "auto_align": False,
            }
        ),
        updates.append,
    )

    result = json.loads(payload)
    assert result["outputs"] == [str(output.resolve())]
    assert output.is_file()
    stats = result["audio_stats"][0]
    assert stats["sample_rate"] == 8_000
    assert stats["channels"] == 2
    assert stats["file_size"] > 0

    events = [json.loads(update) for update in updates]
    assert events[0]["key"] == "loading_song"
    assert events[-1]["value"] == 100
    # The key travels untranslated because Pyodide has no Qt catalogue.
    assert events[-1]["values"]["path"] == str(output)


def test_silent_audio_reports_null_rather_than_negative_infinity(tmp_path: Path):
    """JSON has no infinity, and a fully cancelled stem analyses to -inf dBFS."""
    sample_rate = 8_000
    silence = np.zeros((sample_rate, 2), dtype=np.float32)
    song = _write(tmp_path / "song.wav", silence, sample_rate)
    accompaniment = _write(tmp_path / "acc.wav", silence, sample_rate)
    output = tmp_path / "out.wav"

    payload = bridge.run_reference(
        json.dumps(
            {
                "song": str(song),
                "accompaniment": str(accompaniment),
                "output": str(output),
                "auto_align": False,
            }
        )
    )

    stats = json.loads(payload)["audio_stats"][0]
    assert stats["peak_dbfs"] is None
    assert stats["rms_dbfs"] is None


def test_timeline_edits_round_trip_through_json():
    analysis = {
        "duration_seconds": 10.0,
        "clips": [
            {
                "kind": "unmatched",
                "stage_start": 0.0,
                "stage_end": 10.0,
                "source": None,
                "source_index": None,
                "source_start": 0.0,
                "source_end": 0.0,
                "confidence": 0.0,
                "enabled": False,
                "manual": False,
            }
        ],
        "missing_sources": [],
    }
    clip = {
        "kind": "song",
        "stage_start": 2.0,
        "stage_end": 6.0,
        "source": "/work/song.wav",
        "source_index": 0,
        "source_start": 0.0,
        "source_end": 4.0,
        "confidence": 0.0,
        "enabled": True,
        "manual": True,
    }

    added = json.loads(bridge.add_timeline_clip(json.dumps({"analysis": analysis, "clip": clip})))
    kinds = [entry["kind"] for entry in added["analysis"]["clips"]]
    assert kinds.count("song") == 1
    index = kinds.index("song")

    disabled = json.loads(
        bridge.edit_timeline_clip(
            json.dumps(
                {"analysis": added["analysis"], "index": index, "changes": {"enabled": False}}
            )
        )
    )
    assert disabled["analysis"]["clips"][index]["enabled"] is False

    removed = json.loads(
        bridge.remove_timeline_clip(json.dumps({"analysis": added["analysis"], "index": index}))
    )
    assert all(entry["kind"] != "song" for entry in removed["analysis"]["clips"])


def test_editing_a_stage_range_past_the_recording_is_rejected():
    analysis = {
        "duration_seconds": 10.0,
        "clips": [
            {
                "kind": "unmatched",
                "stage_start": 0.0,
                "stage_end": 10.0,
                "source": None,
                "source_index": None,
                "source_start": 0.0,
                "source_end": 0.0,
                "confidence": 0.0,
                "enabled": False,
                "manual": False,
            }
        ],
        "missing_sources": [],
    }
    with pytest.raises(ValueError):
        bridge.edit_timeline_clip(
            json.dumps({"analysis": analysis, "index": 0, "changes": {"stage_end": 99.0}})
        )


@pytest.mark.parametrize(
    ("seconds", "fits"),
    [(300.0, True), (7200.0, False)],
)
def test_full_stage_estimate_refuses_what_wasm_cannot_hold(seconds, fits):
    payload = json.loads(
        bridge.estimate_full_stage(
            json.dumps(
                {
                    "sample_rate": 44_100,
                    "stage_seconds": seconds,
                    "longest_source_seconds": 300.0,
                    "file_bytes": 50_000_000,
                }
            )
        )
    )
    assert payload["fits"] is fits
    assert payload["budget_bytes"] == limits.WASM_BUDGET_BYTES
    assert math.isclose(payload["fraction"], payload["peak_bytes"] / payload["budget_bytes"])


def test_a_single_song_of_ordinary_length_fits_comfortably():
    payload = json.loads(
        bridge.estimate_reference(
            json.dumps(
                {
                    "sample_rate": 44_100,
                    "song_seconds": 300.0,
                    "accompaniment_seconds": 300.0,
                    "file_bytes": 60_000_000,
                }
            )
        )
    )
    assert payload["fits"] is True
    assert payload["tight"] is False


def test_render_stage_accepts_an_edited_timeline(tmp_path: Path):
    """The page hands back the analysis it edited, so the render must reload it."""
    sample_rate = 8_000
    random = np.random.default_rng(11)
    time = np.arange(sample_rate * 4) / sample_rate
    source = np.stack([0.3 * np.sin(2 * np.pi * 180 * time)] * 2, axis=1).astype(np.float32)
    stage = random.normal(0, 0.01, (8 * sample_rate, 2)).astype(np.float32)
    stage[2 * sample_rate : 6 * sample_rate] += source
    stage_path = _write(tmp_path / "stage.wav", stage, sample_rate)
    source_path = _write(tmp_path / "source.wav", source, sample_rate)
    output = tmp_path / "render.wav"
    analysis = {
        "duration_seconds": 8.0,
        "clips": [
            {
                "kind": "unmatched",
                "stage_start": 0.0,
                "stage_end": 2.0,
                "source": None,
                "source_index": None,
                "source_start": 0.0,
                "source_end": 0.0,
                "confidence": 0.0,
                "enabled": False,
                "manual": False,
            },
            {
                "kind": "song",
                "stage_start": 2.0,
                "stage_end": 6.0,
                "source": str(source_path.resolve()),
                "source_index": 0,
                "source_start": 0.0,
                "source_end": 4.0,
                "confidence": 0.9,
                "enabled": True,
                "manual": False,
            },
        ],
        "missing_sources": [],
    }

    payload = json.loads(
        bridge.render_stage(
            json.dumps(
                {
                    "stage": str(stage_path),
                    "sources": [str(source_path)],
                    "output": str(output),
                    "analysis": analysis,
                    "auto_align": False,
                }
            )
        )
    )

    assert payload["outputs"] == [str(output.resolve())]
    assert output.is_file()
    rendered, _rate = sf.read(output, dtype="float32", always_2d=True)
    matched = slice(2 * sample_rate, 6 * sample_rate)
    untouched = slice(0, 2 * sample_rate)
    # The matched span loses the source; the unmatched span keeps the stage.
    assert np.sqrt(np.mean(rendered[matched] ** 2)) < np.sqrt(np.mean(stage[matched] ** 2))
    assert np.allclose(rendered[untouched], stage[untouched], atol=2e-4)


def test_probe_reads_the_header_of_a_supported_file(tmp_path: Path):
    path = _write(tmp_path / "probe.flac", np.zeros((16_000, 2), dtype=np.float32), 8_000)

    payload = json.loads(bridge.probe_audio(json.dumps({"path": str(path)})))

    assert payload["supported"] is True
    assert payload["sample_rate"] == 8_000
    assert payload["channels"] == 2
    assert payload["seconds"] == pytest.approx(2.0)


def test_probe_reports_an_unreadable_container_instead_of_raising(tmp_path: Path):
    """The page decodes those with the browser, the way Qt Multimedia does on the desktop."""
    path = tmp_path / "clip.m4a"
    path.write_bytes(b"\x00\x00\x00\x18ftypM4A not really a container")

    payload = json.loads(bridge.probe_audio(json.dumps({"path": str(path)})))

    assert payload["supported"] is False
    assert payload["reason"]
