from __future__ import annotations

import argparse
import io
import logging
import signal
import sys
from contextlib import redirect_stdout
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from app.version import __version__
from features.neural_separation import (
    DEFAULT_MODEL_ID,
    NeuralJob,
    model_catalog,
    run_neural_job,
)
from features.reference_removal import ReferenceJob, run_reference_job
from shared.branding import APPLICATION_NAME, ORGANIZATION_NAME
from shared.i18n import SUPPORTED_LANGUAGES, install_language
from shared.jobs import SIGMA_CHOICES, STRENGTH_MAXIMUM, STRENGTH_MINIMUM, STRENGTH_RANGE
from shared.logging import configure_logging, set_log_level
from shared.processing import CancellationToken, ProcessingCancelled, ProgressEvent

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="purivox", description="Vocal and accompaniment separation"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command")

    reference = commands.add_parser("mr", help="reference-guided vocal extraction")
    reference.add_argument("song", type=Path)
    reference.add_argument("accompaniment", type=Path)
    reference.add_argument("output", type=Path)
    reference.add_argument(
        "--strength",
        type=int,
        choices=STRENGTH_RANGE,
        default=75,
        metavar=f"{STRENGTH_MINIMUM}..{STRENGTH_MAXIMUM}",
    )
    reference.add_argument("--sigma", type=int, choices=SIGMA_CHOICES, default=3)
    reference.add_argument("--align", action=argparse.BooleanOptionalAction, default=True)
    reference.add_argument(
        "--center-extraction",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="apply phantom-center vocal extraction after reference cancellation",
    )
    reference.add_argument(
        "--open-mic-focus",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="preserve a quiet open mic while suppressing closed-mic sections; requires --center-extraction",
    )
    reference.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default=SUPPORTED_LANGUAGES[0])

    neural = commands.add_parser("ai", help="MDX-Net vocal extraction")
    neural.add_argument("song", type=Path)
    neural.add_argument("--output-dir", type=Path)
    neural.add_argument(
        "--model", choices=[entry.id for entry in model_catalog()], default=DEFAULT_MODEL_ID
    )
    neural.add_argument("--models-dir", type=Path)
    neural.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default=SUPPORTED_LANGUAGES[0])
    return parser


def _print_progress(event: ProgressEvent) -> None:
    logger.info("progress: %3d%%  %s", event.value, event.message)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    if args.command is None:
        # The open-source QFluentWidgets package prints a Pro advertisement at
        # import time.  Keep normal application startup output clean without
        # changing or patching the installed dependency.
        with redirect_stdout(io.StringIO()):
            from entrypoints.gui import run_gui

        return run_gui(args.selftest)
    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    app.setApplicationName(APPLICATION_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    with redirect_stdout(io.StringIO()):
        from shared.config import cfg, load_config

    load_config()
    set_log_level(str(cfg.log_level.value))
    install_language(args.lang)
    token = CancellationToken()
    previous_handler = signal.signal(signal.SIGINT, lambda *_unused: token.cancel())
    try:
        if args.command == "mr":
            job = ReferenceJob(
                song=args.song,
                accompaniment=args.accompaniment,
                output=args.output,
                strength=args.strength,
                sigma=args.sigma,
                auto_align=args.align,
                center_extraction=args.center_extraction,
                open_mic_focus=args.open_mic_focus,
            )
            result = run_reference_job(job, token, _print_progress)
        else:
            output_dir = args.output_dir or args.song.expanduser().resolve().parent
            job = NeuralJob(args.song, output_dir, args.model, args.models_dir)
            result = run_neural_job(job, token, _print_progress)
        for output in result.outputs:
            print(output)
        return 0
    except ProcessingCancelled:
        logger.warning("cancelled")
        return 130
    except (FileNotFoundError, KeyError, ValueError) as error:
        logger.error("%s", error)
        return 2
    except Exception as error:
        logger.exception("unhandled processing error: %s", error)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)
