"""What the panning estimate is supposed to buy over a fixed matrix.

Every assertion here is a level measured at one frequency, because a filter
shifts phase and a waveform comparison would only measure that.
"""

from __future__ import annotations

import numpy as np

from features.stem_split.dsp.panning import cancel_centre_from_front, separate_centre
from shared.audio import AudioData
from shared.processing import CancellationToken

RATE = 22_050
FRAMES = RATE * 4
VOCAL_HZ, GUITAR_HZ, BASS_HZ = 330.0, 587.0, 73.0
_TIME = np.arange(FRAMES) / RATE


def _audio(samples: np.ndarray) -> AudioData:
    return AudioData(np.ascontiguousarray(np.atleast_2d(samples), dtype=np.float32), RATE)


def _level(values: np.ndarray, frequency: float) -> float:
    """How much of one frequency a signal carries, regardless of its phase."""
    reference = np.exp(-2j * np.pi * frequency * _TIME[: values.size])
    return float(np.abs(np.mean(np.asarray(values) * reference)))


def _change_db(values: np.ndarray, reference: np.ndarray, frequency: float) -> float:
    return 20.0 * np.log10(
        max(_level(values, frequency), 1e-12) / max(_level(reference, frequency), 1e-12)
    )


def _parts() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vocal = 0.5 * np.sin(2 * np.pi * VOCAL_HZ * _TIME) * (1 + 0.3 * np.sin(2 * np.pi * 3 * _TIME))
    guitar = 0.4 * np.sin(2 * np.pi * GUITAR_HZ * _TIME)
    bass = 0.3 * np.sin(2 * np.pi * BASS_HZ * _TIME)
    return vocal, guitar, bass


def _split(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    stereo = _audio(np.stack([left, right]))
    centre = _audio(np.zeros((1, FRAMES)))
    instrumental = _audio(np.zeros((2, FRAMES)))
    separate_centre(stereo, centre, instrumental, CancellationToken())
    return centre.samples[0], instrumental.samples[0]


def test_a_centred_lead_leaves_the_instrumental_and_the_panned_parts_stay():
    vocal, guitar, bass = _parts()
    left, right = vocal + 0.9 * guitar + bass, vocal + 0.3 * guitar + bass

    centre, instrumental = _split(left, right)

    assert _change_db(instrumental, left, VOCAL_HZ) < -30.0
    assert _change_db(instrumental, left, GUITAR_HZ) > -1.0
    assert _change_db(centre, left, VOCAL_HZ) > -1.0
    assert _change_db(centre, left, GUITAR_HZ) < -30.0


def test_the_centred_bass_stays_in_the_instrumental():
    """The kick and the bass are centred by convention, not because they lead.

    Taking them out with the vocal is the complaint every phase-cancellation
    karaoke track attracts, and what the fixed mid attenuation Atome uses does.
    """
    vocal, guitar, bass = _parts()
    left, right = vocal + 0.9 * guitar + bass, vocal + 0.3 * guitar + bass

    centre, instrumental = _split(left, right)

    assert _change_db(instrumental, left, BASS_HZ) > -1.0
    assert _change_db(centre, left, BASS_HZ) < -30.0


def test_a_source_panned_past_the_tolerance_is_not_treated_as_the_lead():
    vocal, guitar, bass = _parts()
    # Two thirds of the way to one side: a doubled line or a harmony, which
    # belongs with the arrangement rather than with the lead.
    left, right = 0.92 * vocal + 0.9 * guitar + bass, 0.39 * vocal + 0.3 * guitar + bass

    _centre, instrumental = _split(left, right)

    assert _change_db(instrumental, left, VOCAL_HZ) > -3.0


def test_the_front_pair_loses_a_filtered_centre_leak():
    """One real number cannot cancel a leak that is a filter; a ratio per bin can."""
    vocal, guitar, bass = _parts()
    response = np.array([0.0, 0.0, 0.6, -0.25, 0.1])
    front_left = guitar + np.convolve(vocal, response)[:FRAMES]
    front_right = bass + np.convolve(vocal, response * 0.8)[:FRAMES]
    silence = np.zeros(FRAMES)
    source = _audio(np.stack([front_left, front_right, vocal, silence, silence, silence]))
    destination = _audio(np.zeros((2, FRAMES)))

    cancel_centre_from_front(source, destination, (0, 1), 2, CancellationToken())

    assert _change_db(destination.samples[0], front_left, VOCAL_HZ) < -30.0
    assert _change_db(destination.samples[0], front_left, GUITAR_HZ) > -1.0
