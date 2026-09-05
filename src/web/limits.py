from __future__ import annotations

from dataclasses import dataclass

# Pyodide compiles to wasm32, whose linear memory tops out at 4 GiB, and
# Emscripten's temporary filesystem lives inside that same memory.  The
# `np.memmap` discipline the pipelines follow therefore saves nothing in a
# browser: every `create_pcm_audio` allocation is resident, and so is every
# uploaded file.  Leave room for the interpreter, numpy/scipy and allocator
# fragmentation, and spend what is left on audio.
WASM_BUDGET_BYTES = 2_600_000_000
# Above this fraction of the budget the estimate is close enough to the ceiling
# that a browser under memory pressure may still fail; the page warns instead of
# refusing, because the estimate is an upper bound and not a measurement.
WARN_FRACTION = 0.6
# `AudioData` is planar float32 whatever the source was recorded at.
BYTES_PER_SAMPLE = 4
# A finished stem is written to the Emscripten filesystem, which is the same
# linear memory, at the source's own depth; 24-bit stereo is 6 bytes a frame.
# Only the "both" export holds two of them at once.
WAV_BYTES_PER_SAMPLE = 3
# One `_reference_cancel` block expands `_SPECTRAL_CELL_BUDGET` (4 million)
# spectral cells into a handful of complex and real work arrays.  Browsers run
# the single-worker layout, which spends the whole budget on one block.
DSP_WORKING_SET_BYTES = 500_000_000


@dataclass(frozen=True, slots=True)
class MemoryEstimate:
    """An upper bound on what one job would hold resident, against the budget."""

    peak_bytes: int
    budget_bytes: int = WASM_BUDGET_BYTES

    @property
    def fits(self) -> bool:
        return self.peak_bytes <= self.budget_bytes

    @property
    def tight(self) -> bool:
        return self.peak_bytes > self.budget_bytes * WARN_FRACTION


def buffer_bytes(sample_rate: int, seconds: float, channels: int = 2) -> int:
    """What one full-length decoded buffer of this audio costs.

    Every pipeline upmixes to stereo through `AudioData.stereo()` before it
    allocates anything, so the channel count of the source does not carry.
    """
    if sample_rate <= 0 or seconds < 0 or channels <= 0:
        raise ValueError("sample rate, duration and channel count must be positive")
    return int(channels * sample_rate * BYTES_PER_SAMPLE * seconds)


def written_bytes(sample_rate: int, seconds: float, channels: int = 2) -> int:
    """What one exported stem occupies in the browser filesystem."""
    if sample_rate <= 0 or seconds < 0 or channels <= 0:
        raise ValueError("sample rate, duration and channel count must be positive")
    return int(channels * sample_rate * WAV_BYTES_PER_SAMPLE * seconds)


def reference_peak_bytes(
    sample_rate: int,
    song_seconds: float,
    accompaniment_seconds: float,
    file_bytes: int = 0,
    both_tracks: bool = False,
) -> MemoryEstimate:
    """Estimate the peak for `run_reference_job`.

    It holds the song, the reference resampled onto the song's timeline and one
    more full-length buffer at once - the alignment scratch first, then the
    processed output - on top of the block working set.  The backing track is
    formed in that same output buffer, so exporting both stems costs no extra
    buffer, only the first stem's file staying on the filesystem.
    """
    song = buffer_bytes(sample_rate, song_seconds)
    reference = buffer_bytes(sample_rate, accompaniment_seconds)
    written = written_bytes(sample_rate, song_seconds) if both_tracks else 0
    peak = file_bytes + song + reference + max(song, reference) + written
    return MemoryEstimate(peak + DSP_WORKING_SET_BYTES)


def full_stage_peak_bytes(
    sample_rate: int,
    stage_seconds: float,
    longest_source_seconds: float,
    file_bytes: int = 0,
    both_tracks: bool = False,
) -> MemoryEstimate:
    """Estimate the peak for `run_full_stage_job`.

    The render keeps the stage recording and a full-length copy of the output
    for its whole duration, and adds one decoded source plus two clip-length
    buffers while it works through a clip.  A clip is never longer than the
    source it came from, so the longest source bounds all three.
    """
    stage = buffer_bytes(sample_rate, stage_seconds)
    source = buffer_bytes(sample_rate, longest_source_seconds)
    written = written_bytes(sample_rate, stage_seconds) if both_tracks else 0
    peak = file_bytes + 2 * stage + 3 * source + written
    return MemoryEstimate(peak + DSP_WORKING_SET_BYTES)
