"""The stem-split pipeline: one file in, the stems its layout allows out.

No song source and no reference: this is the other workflow, where the only
thing there is to go on is the mix itself and how its channels relate.  Which
stems come out is decided by the channel count, because that is what decides
what can honestly be separated - a discrete surround master carries its centre
channel, a stereo master only implies one.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from features.stem_split.dsp import (
    cancel_centre_from_front,
    channel_peaks,
    copy_channels_into,
    difference,
    downmix_gain,
    downmix_into,
    fit_group,
    lowpass,
    mid_into,
    separate_centre,
    side_into,
    surround_into,
)
from features.stem_split.dsp.matrix import FRONT_CENTER, FRONT_LEFT, FRONT_RIGHT, LOW_FREQUENCY
from features.stem_split.dsp.panning import ProgressFraction
from features.stem_split.models import (
    PRESENCE_HZ,
    StemKind,
    StemLayout,
    StemSplitJob,
    StemSplitResult,
    layout_for,
    layout_stems,
    stem_path,
)
from shared.audio import AudioData, AudioStats, create_pcm_audio, export_audio, read_audio
from shared.processing import CancellationToken, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)

# Decoding is one read of the file; everything after it is the rendering, which
# the stems divide between them.
_DECODED = 10
_RENDERED = 99
# Where one stem's share of the bar is split between making it and writing it.
_RENDER_SHARE = 0.6
_ANALYSING = 0.7
_SAVING = 0.85

Rendering = tuple[StemKind, Path, AudioData]


@dataclass(frozen=True, slots=True)
class _Bar:
    """One stem's share of the progress bar, so it only ever moves forward."""

    progress: ProgressCallback
    output_dir: Path
    source: Path
    total: int

    def value(self, index: int, fraction: float) -> int:
        span = (_RENDERED - _DECODED) / max(self.total, 1)
        return min(_RENDERED, round(_DECODED + span * (index + fraction)))

    def path(self, kind: StemKind) -> Path:
        return stem_path(self.source, self.output_dir, kind)

    def start(self, index: int, kind: StemKind) -> Path:
        """Announce the stem about to be yielded, and name the file it goes to."""
        path = self.path(kind)
        self._render(index, path.name, 0.0)
        return path

    def tracker(self, index: int, kind: StemKind) -> ProgressFraction:
        name = self.path(kind).name
        return lambda fraction: self._render(index, name, fraction)

    def _render(self, index: int, name: str, fraction: float) -> None:
        report_progress(
            self.progress,
            self.value(index, _RENDER_SHARE * fraction),
            "stem_rendering",
            current=index + 1,
            total=self.total,
            name=name,
        )


def _surround_stems(
    job: StemSplitJob,
    source: AudioData,
    bar: _Bar,
    token: CancellationToken,
) -> Iterator[Rendering]:
    """A discrete surround master, decoded channel by channel.

    Nothing here is estimated except the leak of the centre channel into the
    front pair: the ambience, the lead and the sub are separate channels on the
    master, which is why this path is worth taking when a file offers it.
    """
    frames, rate, depth = source.frames, source.sample_rate, source.bit_depth
    gain = downmix_gain(channel_peaks(source, token))
    if gain < 1.0:
        logger.info("the fold-down is held %.2f dB down to fit", 20.0 * math.log10(gain))
    pair = create_pcm_audio(2, frames, rate, depth)
    mono = create_pcm_audio(1, frames, rate, depth)
    try:
        path = bar.start(0, StemKind.SURROUND)
        surround_into(pair, source, token)
        yield StemKind.SURROUND, path, pair

        path = bar.start(1, StemKind.CENTER)
        copy_channels_into(mono, source, (FRONT_CENTER,), token)
        yield StemKind.CENTER, path, mono

        path = bar.start(2, StemKind.LFE)
        copy_channels_into(mono, source, (LOW_FREQUENCY,), token)
        yield StemKind.LFE, path, mono

        path = bar.start(3, StemKind.FRONT)
        copy_channels_into(pair, source, (FRONT_LEFT, FRONT_RIGHT), token)
        yield StemKind.FRONT, path, pair

        path = bar.start(4, StemKind.FRONT_NO_CENTER)
        # A fresh buffer: the spectral pass adds its blocks into what it is
        # given, so it has to start from silence rather than the last stem.
        cleaned = create_pcm_audio(2, frames, rate, depth)
        try:
            cancel_centre_from_front(
                source,
                cleaned,
                (FRONT_LEFT, FRONT_RIGHT),
                FRONT_CENTER,
                token,
                bar.tracker(4, StemKind.FRONT_NO_CENTER),
            )
            yield StemKind.FRONT_NO_CENTER, path, cleaned
        finally:
            cleaned.cleanup()

        # The fold-down and its two bands are one decomposition - the bands add
        # back up to it - so all three are rendered before any of them is
        # written, and held under full scale by one shared factor.
        downmix = bar.start(5, StemKind.DOWNMIX)
        downmix_into(pair, source, gain, token)
        low = create_pcm_audio(2, frames, rate, depth)
        high = create_pcm_audio(2, frames, rate, depth)
        try:
            lowpass(pair, low, job.crossover_hz, token)
            difference(high, pair, low, token)
            fit_group((pair, low, high), token)
            yield StemKind.DOWNMIX, downmix, pair
            yield StemKind.LOW, bar.start(6, StemKind.LOW), low
            yield StemKind.HIGH, bar.start(7, StemKind.HIGH), high
        finally:
            high.cleanup()
            low.cleanup()
    finally:
        mono.cleanup()
        pair.cleanup()


def _stereo_stems(
    job: StemSplitJob,
    source: AudioData,
    bar: _Bar,
    token: CancellationToken,
) -> Iterator[Rendering]:
    """A stereo master, where the centre is implied by the two channels rather than carried."""
    stereo = source.stereo()
    frames, rate, depth = stereo.frames, stereo.sample_rate, stereo.bit_depth
    centre = create_pcm_audio(1, frames, rate, depth)
    instrumental = create_pcm_audio(2, frames, rate, depth)
    try:
        path = bar.start(0, StemKind.CENTER)
        separate_centre(stereo, centre, instrumental, token, bar.tracker(0, StemKind.CENTER))
        # The centre and what is left of the mix without it are the two halves
        # of one split, so they carry one gain between them.
        fit_group((centre, instrumental), token)
        yield StemKind.CENTER, path, centre
        yield StemKind.INSTRUMENTAL, bar.start(1, StemKind.INSTRUMENTAL), instrumental
    finally:
        instrumental.cleanup()
        centre.cleanup()
    # Both are bounded by the loudest channel of the mix, so neither can pass
    # full scale unless the mix already did, and they reuse one buffer.
    mono = create_pcm_audio(1, frames, rate, depth)
    try:
        path = bar.start(2, StemKind.SIDE)
        side_into(mono, stereo, token)
        yield StemKind.SIDE, path, mono

        path = bar.start(3, StemKind.MID)
        mid_into(mono, stereo, token)
        yield StemKind.MID, path, mono
    finally:
        mono.cleanup()
    low = create_pcm_audio(2, frames, rate, depth)
    high = create_pcm_audio(2, frames, rate, depth)
    try:
        path = bar.start(4, StemKind.LOW)
        lowpass(stereo, low, job.crossover_hz, token)
        difference(high, stereo, low, token)
        fit_group((low, high), token)
        yield StemKind.LOW, path, low
        yield StemKind.HIGH, bar.start(5, StemKind.HIGH), high
    finally:
        high.cleanup()
        low.cleanup()


def _mono_stems(
    job: StemSplitJob,
    source: AudioData,
    bar: _Bar,
    token: CancellationToken,
) -> Iterator[Rendering]:
    """One channel has no stereo image to read, so it is split by frequency alone.

    Three complementary bands rather than three filters: the presence band is
    the difference of the two low-passes, so the three add back up to the
    recording instead of overlapping around each corner.
    """
    frames, rate, depth = source.frames, source.sample_rate, source.bit_depth
    presence = create_pcm_audio(1, frames, rate, depth)
    low = create_pcm_audio(1, frames, rate, depth)
    middle = create_pcm_audio(1, frames, rate, depth)
    high = create_pcm_audio(1, frames, rate, depth)
    try:
        path = bar.start(0, StemKind.LOW)
        lowpass(source, presence, PRESENCE_HZ, token)
        lowpass(source, low, job.crossover_hz, token)
        difference(middle, presence, low, token)
        difference(high, source, presence, token)
        fit_group((low, middle, high), token)
        yield StemKind.LOW, path, low
        yield StemKind.MID_BAND, bar.start(1, StemKind.MID_BAND), middle
        yield StemKind.HIGH, bar.start(2, StemKind.HIGH), high
    finally:
        high.cleanup()
        middle.cleanup()
        low.cleanup()
        presence.cleanup()


_SPLITTERS = {
    StemLayout.SURROUND: _surround_stems,
    StemLayout.STEREO: _stereo_stems,
    StemLayout.MONO: _mono_stems,
}


def run_stem_split_job(
    job: StemSplitJob,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> StemSplitResult:
    """Split one recording into stems and write them beside each other."""
    source_path = job.source.expanduser().resolve()
    output_dir = job.output_dir.expanduser().resolve()
    logger.info("starting stem split: %s -> %s", source_path, output_dir)
    report_progress(progress, 0, "stem_reading")
    audio = read_audio(source_path, token)
    try:
        layout = layout_for(audio.channels)
        kinds = layout_stems(layout)
        logger.info(
            "%d channels: splitting as %s into %d stems", audio.channels, layout, len(kinds)
        )
        report_progress(progress, _DECODED, f"stem_layout_{layout.value}")
        bar = _Bar(progress, output_dir, source_path, len(kinds))
        outputs: list[Path] = []
        stats: list[AudioStats] = []
        with closing(_SPLITTERS[layout](job, audio, bar, token)) as stems:
            for index, (kind, path, stem) in enumerate(stems):
                token.raise_if_cancelled()
                stats.append(
                    export_audio(
                        stem,
                        path,
                        token,
                        progress,
                        bar.value(index, _ANALYSING),
                        bar.value(index, _SAVING),
                    )
                )
                outputs.append(path.resolve())
                logger.info("wrote the %s stem: %s", kind.value, path)
        report_progress(progress, 100, "done_status", path=outputs[0])
        return StemSplitResult(layout, kinds, tuple(outputs), tuple(stats))
    finally:
        audio.cleanup()
