from __future__ import annotations

import logging
import mmap
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from shared.processing import CancellationToken

logger = logging.getLogger(__name__)

# The PCM depths the WAV writer can produce.  Anything decoded from a wider or
# floating-point source is written at 24 bits, which is the practical ceiling
# for a delivery file.
WAV_BIT_DEPTHS = (16, 24)
DEFAULT_BIT_DEPTH = 24
# Every streaming loop in the project reads, writes and copies audio in blocks
# of this many frames, so a long recording never becomes a resident array.
BLOCK_FRAMES = 262_144
# Container suffixes offered by the file dialogs and accepted by the automatic
# accompaniment finder.
AUDIO_EXTENSIONS = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus")


def _subtype_bit_depth(subtype: str) -> int:
    """The WAV depth a source of this libsndfile subtype is written back out at.

    libsndfile names its PCM subtypes by width, so an 8- or 16-bit recording
    keeps 16 bits.  Everything else - wider PCM, float, and every lossy format,
    which all decode to float - is written at 24.
    """
    return 16 if subtype in {"PCM_S8", "PCM_U8", "PCM_16"} else DEFAULT_BIT_DEPTH


def _mapping_of(values: np.ndarray) -> mmap.mmap | None:
    """Find the mmap object backing a (possibly sliced or transposed) array."""
    base: object = values
    mapping = None
    while isinstance(base, np.ndarray):
        mapping = getattr(base, "_mmap", mapping)
        if getattr(base, "base", None) is None:
            break
        base = base.base
    return mapping


def release_mapped_pages(values: np.ndarray) -> None:
    """Flush a disk mapping and let the kernel evict its resident pages.

    This is a hint, so a platform that cannot honour it must not fail the job
    over it.  Emscripten maps a file that already lives in the same heap as the
    array, so there is nothing to flush and nothing to evict, and its `msync`
    reports a bad descriptor instead of succeeding.
    """
    mapping = _mapping_of(values)
    if mapping is None:
        return
    try:
        mapping.flush()
    except OSError as error:
        logger.debug("this platform cannot flush a mapping: %s", error)
        return
    if hasattr(mapping, "madvise") and hasattr(mmap, "MADV_DONTNEED"):
        mapping.madvise(mmap.MADV_DONTNEED)


@dataclass(frozen=True, slots=True)
class AudioData:
    """Planar float32 audio in the range normally used by PCM audio."""

    samples: np.ndarray
    sample_rate: int
    backing_path: Path | None = None
    bit_depth: int = DEFAULT_BIT_DEPTH
    """What the source was recorded at, and what an export of it is written at."""

    def __post_init__(self) -> None:
        samples = np.asarray(self.samples)
        if samples.ndim != 2 or samples.shape[0] == 0 or samples.shape[1] == 0:
            raise ValueError("audio samples must have shape [channels, frames]")
        if self.sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        if self.bit_depth not in WAV_BIT_DEPTHS:
            raise ValueError(f"bit depth must be one of {WAV_BIT_DEPTHS}")
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        object.__setattr__(self, "samples", samples)

    @property
    def channels(self) -> int:
        return int(self.samples.shape[0])

    @property
    def frames(self) -> int:
        return int(self.samples.shape[1])

    def stereo(self) -> AudioData:
        # __post_init__ rejects an empty channel axis, so the input is mono or wider.
        if self.channels == 1:
            return AudioData(
                np.repeat(self.samples, 2, axis=0),
                self.sample_rate,
                self.backing_path,
                self.bit_depth,
            )
        return AudioData(self.samples[:2], self.sample_rate, self.backing_path, self.bit_depth)

    def cleanup(self) -> None:
        """Close and remove an owned temporary PCM mapping."""
        mapping = _mapping_of(self.samples)
        if mapping is not None:
            mapping.close()
        if self.backing_path is not None:
            self.backing_path.unlink(missing_ok=True)

    def release_pages(self) -> None:
        """Flush a disk mapping and let the kernel evict its resident pages."""
        release_mapped_pages(self.samples)


def create_pcm_audio(
    channels: int,
    frames: int,
    sample_rate: int,
    bit_depth: int = DEFAULT_BIT_DEPTH,
) -> AudioData:
    """Allocate a planar float32 audio buffer in a temporary disk mapping."""
    if channels <= 0 or frames <= 0 or sample_rate <= 0:
        raise ValueError("channels, frames and sample rate must be positive")
    fd, name = tempfile.mkstemp(prefix="purivox-", suffix=".float32.pcm")
    os.close(fd)
    path = Path(name)
    try:
        samples = np.memmap(path, mode="w+", dtype=np.float32, shape=(channels, frames))
        return AudioData(samples, sample_rate, path, bit_depth)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _read_with_soundfile(path: Path, token: CancellationToken) -> AudioData:
    logger.debug("decoding with SoundFile: %s", path)
    with sf.SoundFile(path) as source:
        if source.frames <= 0 or source.channels <= 0:
            raise ValueError(f"audio file contains no samples: {path}")
        audio = create_pcm_audio(
            source.channels, source.frames, source.samplerate, _subtype_bit_depth(source.subtype)
        )
        try:
            start = 0
            for block in source.blocks(blocksize=BLOCK_FRAMES, dtype="float32", always_2d=True):
                token.raise_if_cancelled()
                end = start + block.shape[0]
                audio.samples[:, start:end] = block.T
                start = end
            audio.release_pages()
            logger.info(
                "decoded with SoundFile: %s (%d Hz, %d channels, %d frames, %d-bit)",
                path,
                audio.sample_rate,
                audio.channels,
                audio.frames,
                audio.bit_depth,
            )
            return audio
        except BaseException:
            audio.cleanup()
            raise


def _read_with_qt(path: Path, token: CancellationToken) -> AudioData:
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

    logger.debug("decoding with Qt Multimedia: %s", path)
    decoder = QAudioDecoder()
    decoder.setSource(QUrl.fromLocalFile(str(path)))
    loop = QEventLoop()
    fd, temporary_name = tempfile.mkstemp(prefix="purivox-decoder-", suffix=".pcm")
    raw_output = os.fdopen(fd, "wb")
    temporary_path = Path(temporary_name)
    frames = 0
    sample_rate = 0
    channels = 0
    error = ""
    error_code = QAudioDecoder.Error.NoError

    def consume() -> None:
        nonlocal sample_rate, channels, error, frames
        buffer = decoder.read()
        fmt = buffer.format()
        sample_rate = fmt.sampleRate()
        channels = fmt.channelCount()
        dtype: np.dtype | None = None
        scale = 1.0
        if fmt.sampleFormat() == QAudioFormat.SampleFormat.Float:
            dtype = np.dtype("<f4")
        elif fmt.sampleFormat() == QAudioFormat.SampleFormat.Int16:
            dtype, scale = np.dtype("<i2"), 32768.0
        elif fmt.sampleFormat() == QAudioFormat.SampleFormat.Int32:
            dtype, scale = np.dtype("<i4"), 2147483648.0
        elif fmt.sampleFormat() == QAudioFormat.SampleFormat.UInt8:
            raw = np.frombuffer(buffer.constData(), dtype=np.uint8).astype(np.float32)
            converted = ((raw - 128.0) / 128.0).reshape(-1, channels)
            raw_output.write(converted.astype(np.float32, copy=False).tobytes())
            frames += converted.shape[0]
            return
        else:
            error = "unsupported decoded sample format"
            decoder.stop()
            loop.quit()
            return
        raw = np.frombuffer(buffer.constData(), dtype=dtype).astype(np.float32)
        if scale != 1.0:
            raw /= scale
        converted = raw.reshape(-1, channels)
        raw_output.write(converted.astype(np.float32, copy=False).tobytes())
        frames += converted.shape[0]

    decoder.bufferReady.connect(consume)
    decoder.finished.connect(loop.quit)

    def decoder_failed(code: QAudioDecoder.Error) -> None:
        nonlocal error, error_code
        error_code = code
        error = decoder.errorString()
        loop.quit()

    decoder.error.connect(decoder_failed)
    poll = QTimer()
    poll.setInterval(100)

    def poll_cancel() -> None:
        if token.cancelled:
            decoder.stop()
            loop.quit()

    poll.timeout.connect(poll_cancel)
    poll.start()
    decoder.start()
    loop.exec()
    poll.stop()
    raw_output.close()
    try:
        token.raise_if_cancelled()
        if error or frames <= 0 or channels <= 0 or sample_rate <= 0:
            logger.error(
                "Qt Multimedia decoder failed: %s (code=%s, message=%s)",
                path,
                error_code.name,
                error or "no decoded audio frames",
            )
            raise RuntimeError(error or f"Qt could not decode {path}")
        interleaved = np.memmap(
            temporary_path, mode="r+", dtype=np.float32, shape=(frames, channels)
        )
        # The depth stays at the default: `QAudioFormat.SampleFormat` describes
        # what this decoder chose to hand back, not what the file holds, and it
        # only ever sees the compressed containers libsndfile turned down.
        audio = AudioData(interleaved.T, sample_rate, temporary_path)
        logger.info(
            "decoded with Qt Multimedia: %s (%d Hz, %d channels, %d frames, %d-bit)",
            path,
            audio.sample_rate,
            audio.channels,
            audio.frames,
            audio.bit_depth,
        )
        return audio
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def read_audio(path: str | Path, token: CancellationToken | None = None) -> AudioData:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    cancel = token or CancellationToken()
    try:
        return _read_with_soundfile(source, cancel)
    except (sf.LibsndfileError, RuntimeError) as error:
        logger.info("SoundFile decoder unavailable for %s; trying Qt: %s", source, error)
        return _read_with_qt(source, cancel)


def resample_audio(
    audio: AudioData, target_rate: int, token: CancellationToken | None = None
) -> AudioData:
    cancel = token or CancellationToken()
    cancel.raise_if_cancelled()
    if target_rate <= 0:
        raise ValueError("target sample rate must be positive")
    if audio.sample_rate == target_rate:
        return audio
    logger.info("resampling audio from %d Hz to %d Hz", audio.sample_rate, target_rate)
    fd, temporary_name = tempfile.mkstemp(prefix="purivox-resample-", suffix=".pcm")
    temporary = Path(temporary_name)
    output = os.fdopen(fd, "wb")
    stream = soxr.ResampleStream(
        audio.sample_rate, target_rate, audio.channels, dtype="float32", quality="HQ"
    )
    frames = 0
    try:
        block_size = BLOCK_FRAMES
        for start in range(0, audio.frames, block_size):
            cancel.raise_if_cancelled()
            end = min(start + block_size, audio.frames)
            block = np.asarray(audio.samples[:, start:end].T, dtype=np.float32)
            converted = stream.resample_chunk(block, last=end == audio.frames)
            output.write(converted.astype(np.float32, copy=False).tobytes())
            frames += converted.shape[0]
        output.close()
        if frames <= 0:
            raise ValueError("resampler produced no samples")
        interleaved = np.memmap(
            temporary, mode="r+", dtype=np.float32, shape=(frames, audio.channels)
        )
        return AudioData(interleaved.T, target_rate, temporary, audio.bit_depth)
    except BaseException:
        if not output.closed:
            output.close()
        temporary.unlink(missing_ok=True)
        raise


def write_wav_atomic(
    path: str | Path,
    audio: AudioData,
    token: CancellationToken | None = None,
) -> None:
    """Write `audio` at its own rate and depth, appearing only once complete."""
    cancel = token or CancellationToken()
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp.wav", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    subtype = "PCM_24" if audio.bit_depth == 24 else "PCM_16"
    try:
        with sf.SoundFile(
            temporary,
            mode="w",
            samplerate=audio.sample_rate,
            channels=audio.channels,
            format="WAV",
            subtype=subtype,
        ) as output:
            interleaved = np.nan_to_num(audio.samples.T, copy=False)
            for start in range(0, audio.frames, BLOCK_FRAMES):
                cancel.raise_if_cancelled()
                output.write(interleaved[start : start + BLOCK_FRAMES])
        cancel.raise_if_cancelled()
        os.replace(temporary, destination)
        logger.info("wrote WAV atomically: %s", destination)
    finally:
        temporary.unlink(missing_ok=True)
