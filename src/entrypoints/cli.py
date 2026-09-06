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
from features.reference_removal import ReferenceJob, run_reference_job
from shared.branding import APPLICATION_NAME, ORGANIZATION_NAME
from shared.i18n import SUPPORTED_LANGUAGES, install_language
from shared.jobs import (
    SIGMA_CHOICES,
    STRENGTH_MAXIMUM,
    STRENGTH_MINIMUM,
    STRENGTH_RANGE,
    OutputTracks,
)
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
        "--tracks",
        type=OutputTracks,
        choices=list(OutputTracks),
        default=OutputTracks.VOCAL,
    )
    reference.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default=SUPPORTED_LANGUAGES[0])

    download = commands.add_parser("fetch", help="download audio from a link")
    download.add_argument(
        "query",
        nargs="?",
        help="a link to download, or keywords to search YouTube for",
    )
    download.add_argument("--out", type=Path, help="where to save, instead of the download folder")
    # Defaulted in the command rather than here, so the parser does not have to
    # import yt-dlp to describe an option `mr` never uses.
    download.add_argument("--limit", type=int, help="how many search results to list")
    download.add_argument("--pick", type=int, help="download this result of a search, 1-based")
    download.add_argument("--list", action="store_true", help="list what has been downloaded")
    download.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default=SUPPORTED_LANGUAGES[0])
    return parser


def _print_progress(event: ProgressEvent) -> None:
    logger.info("progress: %3d%%  %s", event.value, event.message)


def _run_fetch(args: argparse.Namespace, token: CancellationToken) -> int:
    """Download one link, or list what a search or the cache holds.

    Imported here rather than at module scope: yt-dlp costs a tenth of a second
    to import, which `mr` should not pay for a command it does not use.
    """
    from shared.download import (
        SEARCH_LIMIT,
        DownloadCache,
        DownloadUnavailable,
        fetch,
        ffmpeg_available,
        looks_like_url,
        search,
    )

    cache = DownloadCache()
    if args.list:
        for entry in cache.entries():
            print(f"{entry.track.title}\t{entry.path}")
        return 0
    query = (args.query or "").strip()
    if not query:
        logger.error("fetch needs a link, keywords, or --list")
        return 2
    try:
        if looks_like_url(query):
            url = query
        else:
            results = search(query, args.limit or SEARCH_LIMIT)
            if not results:
                logger.error("nothing was found for %s", query)
                return 2
            if args.pick is None:
                for index, track in enumerate(results, start=1):
                    print(f"{index}\t{track.title}\t{track.uploader}\t{track.url}")
                return 0
            if not 1 <= args.pick <= len(results):
                logger.error("--pick must be between 1 and %d", len(results))
                return 2
            url = results[args.pick - 1].url
        if (cached := cache.find(url)) is not None:
            logger.info("already downloaded")
            print(cached.path)
            return 0
        if not ffmpeg_available():
            logger.warning("ffmpeg was not found; the downloaded container is kept as it is")
        directory = args.out.expanduser().resolve() if args.out else cache.directory
        fetched = fetch(url, directory, token, _print_progress)
    except DownloadUnavailable as error:
        logger.error("%s", error)
        return 2
    cache.remember(fetched)
    print(fetched.path)
    return 0


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
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORGANIZATION_NAME)
    configure_logging(log_to_file=True)
    with redirect_stdout(io.StringIO()):
        from shared.config import cfg, load_config

    load_config()
    set_log_level(str(cfg.log_level.value))
    install_language(args.lang)
    token = CancellationToken()
    previous_handler = signal.signal(signal.SIGINT, lambda *_unused: token.cancel())
    try:
        if args.command == "fetch":
            return _run_fetch(args, token)
        job = ReferenceJob(
            song=args.song,
            accompaniment=args.accompaniment,
            output=args.output,
            strength=args.strength,
            sigma=args.sigma,
            auto_align=args.align,
            tracks=args.tracks,
        )
        result = run_reference_job(job, token, _print_progress)
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
