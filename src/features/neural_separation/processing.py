from __future__ import annotations

import logging
from pathlib import Path

from features.neural_separation.catalog import get_model
from features.neural_separation.inference import MdxNet
from features.neural_separation.model_store import ensure_model
from features.neural_separation.models import NeuralJob
from shared.audio import (
    HI_RES_BIT_DEPTH,
    create_pcm_audio,
    prepare_hi_res_output,
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
    song = vocal_audio = background_audio = hi_res_vocal = hi_res_background = None
    try:
        report_progress(progress, 0, job.language, "loading_song")
        song = read_audio(job.song, token).stereo()
        if song.sample_rate != 44_100:
            report_progress(progress, 10, job.language, "ai_resampling")
            resampled = resample_audio(song, 44_100, token)
            song.cleanup()
            song = resampled
        model_path = ensure_model(entry, job.models_dir, job.language, token, progress)
        report_progress(progress, 25, job.language, "ai_loading_model")
        try:
            network = MdxNet(model_path)
        except ProcessingCancelled:
            raise
        except Exception as error:
            raise RuntimeError(tr(job.language, "ai_err_model_load", msg=error)) from error
        report_progress(progress, 27, job.language, "ai_inferring")

        def model_progress(current: int, total: int) -> None:
            value = 27 + int(58 * current / max(total, 1))
            report_progress(progress, value, job.language, "ai_inferring")

        vocal_audio = create_pcm_audio(2, song.frames, 44_100)
        try:
            network.separate(song.samples, token, model_progress, vocal_audio.samples)
        except ProcessingCancelled:
            raise
        except Exception as error:
            raise RuntimeError(tr(job.language, "ai_err_infer", msg=error)) from error
        background_audio = create_pcm_audio(2, song.frames, 44_100)
        block_size = 262_144
        for start in range(0, song.frames, block_size):
            token.raise_if_cancelled()
            end = min(start + block_size, song.frames)
            background_audio.samples[:, start:end] = (
                song.samples[:, start:end] - vocal_audio.samples[:, start:end]
            )
        report_progress(progress, 86, job.language, "preparing_hi_res")
        hi_res_vocal = prepare_hi_res_output(vocal_audio, token)
        report_progress(progress, 90, job.language, "ai_saving")
        write_wav_atomic(vocal_path, hi_res_vocal, HI_RES_BIT_DEPTH, token)
        report_progress(progress, 93, job.language, "preparing_hi_res")
        hi_res_background = prepare_hi_res_output(background_audio, token)
        report_progress(progress, 96, job.language, "ai_saving")
        write_wav_atomic(background_path, hi_res_background, HI_RES_BIT_DEPTH, token)
        report_progress(
            progress,
            100,
            job.language,
            "ai_done",
            vocal=vocal_path,
            background=background_path,
        )
        logger.info("neural job completed: vocal=%s background=%s", vocal_path, background_path)
        return ProcessingResult((vocal_path, background_path))
    finally:
        if hi_res_vocal is vocal_audio:
            hi_res_vocal = None
        if hi_res_background is background_audio:
            hi_res_background = None
        for audio in (hi_res_background, hi_res_vocal, background_audio, vocal_audio, song):
            if audio is not None:
                audio.cleanup()
