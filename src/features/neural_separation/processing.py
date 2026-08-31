from __future__ import annotations

import logging
from pathlib import Path

from features.neural_separation.catalog import get_model
from features.neural_separation.inference import MDXNET_SAMPLE_RATE, MdxNet
from features.neural_separation.model_store import ensure_model
from features.neural_separation.models import NeuralJob
from shared.audio import (
    BLOCK_FRAMES,
    create_pcm_audio,
    read_audio,
    resample_audio,
    write_wav_atomic,
)
from shared.i18n import tr
from shared.processing import (
    CancellationToken,
    ProcessingCancelled,
    ProcessingResult,
    ProgressCallback,
)
from shared.progress import report_progress

logger = logging.getLogger(__name__)


def _validate_distinct(*paths: Path) -> None:
    resolved = [path.expanduser().resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("output path must not overwrite an input file")


def run_neural_job(
    job: NeuralJob,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> ProcessingResult:
    logger.info("starting neural job: song=%s model=%s", job.song, job.model_id)
    entry = get_model(job.model_id)
    base = job.output_dir.expanduser().resolve() / job.song.stem
    vocal_path = Path(str(base) + "_vocal.wav")
    background_path = Path(str(base) + "_background.wav")
    _validate_distinct(job.song, vocal_path, background_path)
    song = vocal_audio = background_audio = vocal_output = background_output = None
    try:
        report_progress(progress, 0, "loading_song")
        song = read_audio(job.song, token).stereo()
        # Every shipped model is trained at 44.1 kHz, so the pipeline runs
        # there and both stems are handed back at the format the song arrived
        # in.  Remember it before the input is resampled away.
        source_rate, source_bit_depth = song.sample_rate, song.bit_depth
        if song.sample_rate != MDXNET_SAMPLE_RATE:
            report_progress(progress, 10, "ai_resampling")
            resampled = resample_audio(song, MDXNET_SAMPLE_RATE, token)
            song.cleanup()
            song = resampled
        model_path = ensure_model(entry, job.models_dir, token, progress)
        report_progress(progress, 25, "ai_loading_model")
        try:
            network = MdxNet(model_path)
        except ProcessingCancelled:
            raise
        except Exception as error:
            raise RuntimeError(tr("ai_err_model_load", msg=error)) from error
        report_progress(progress, 27, "ai_inferring")

        def model_progress(current: int, total: int) -> None:
            value = 27 + int(58 * current / max(total, 1))
            report_progress(progress, value, "ai_inferring")

        vocal_audio = create_pcm_audio(2, song.frames, MDXNET_SAMPLE_RATE, source_bit_depth)
        try:
            network.separate(song.samples, token, model_progress, vocal_audio.samples)
        except ProcessingCancelled:
            raise
        except Exception as error:
            raise RuntimeError(tr("ai_err_infer", msg=error)) from error
        background_audio = create_pcm_audio(2, song.frames, MDXNET_SAMPLE_RATE, source_bit_depth)
        block_size = BLOCK_FRAMES
        for start in range(0, song.frames, block_size):
            token.raise_if_cancelled()
            end = min(start + block_size, song.frames)
            background_audio.samples[:, start:end] = (
                song.samples[:, start:end] - vocal_audio.samples[:, start:end]
            )
        report_progress(progress, 90, "ai_saving")
        vocal_output = resample_audio(vocal_audio, source_rate, token)
        write_wav_atomic(vocal_path, vocal_output, token)
        report_progress(progress, 96, "ai_saving")
        background_output = resample_audio(background_audio, source_rate, token)
        write_wav_atomic(background_path, background_output, token)
        report_progress(
            progress,
            100,
            "ai_done",
            vocal=vocal_path,
            background=background_path,
        )
        logger.info("neural job completed: vocal=%s background=%s", vocal_path, background_path)
        return ProcessingResult((vocal_path, background_path))
    finally:
        # `resample_audio` hands back the same object when the rate already
        # matches, so a stem must not be cleaned up twice.
        if vocal_output is vocal_audio:
            vocal_output = None
        if background_output is background_audio:
            background_output = None
        for audio in (background_output, vocal_output, background_audio, vocal_audio, song):
            if audio is not None:
                audio.cleanup()
