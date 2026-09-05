from __future__ import annotations

import io
import logging
import signal
import sys
from contextlib import redirect_stdout

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.crash_handler import install_crash_handler
from app.version import __version__
from shared.branding import APPLICATION_NAME, ORGANIZATION_NAME, application_icon
from shared.i18n import install_language
from shared.logging import configure_logging, set_log_level

logger = logging.getLogger(__name__)


def run_gui(selftest: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setWindowIcon(application_icon())
    # After the identity, because QStandardPaths derives the data directory the
    # log file lives in from the application and organisation names.
    configure_logging(log_to_file=True)
    install_crash_handler()
    # QFluentWidgets prints a Pro advertisement while its package is imported.
    # Keep stdout reserved for CLI result data even in standalone builds.
    with redirect_stdout(io.StringIO()):
        from shared.config import cfg, load_config

    load_config()
    set_log_level(str(cfg.log_level.value))
    install_language(str(cfg.language.value))
    logger.info("starting GUI")
    from app.main_window import MainWindow

    window = MainWindow()
    window.show()
    if selftest:
        QTimer.singleShot(600, app.quit)
    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda _signum, _frame: app.quit())
    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(250)
    try:
        return app.exec()
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
