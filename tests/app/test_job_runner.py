from __future__ import annotations

from app.job_runner import JobRunner
from shared.processing import ProcessingResult, ProgressEvent


def test_job_runner_reports_progress_and_releases_thread(qtbot):
    runner = JobRunner()
    progress: list[tuple[int, str]] = []
    results: list[object] = []
    runner.progress.connect(lambda value, message: progress.append((value, message)))
    runner.succeeded.connect(results.append)

    def operation(_token, report):
        report(ProgressEvent(42, "working"))
        return ProcessingResult(())

    with qtbot.waitSignals([runner.succeeded, runner.finished], timeout=2_000):
        runner.start(operation)
        assert runner.running

    assert progress == [(42, "working")]
    assert results == [ProcessingResult(())]
    assert not runner.running


def test_job_runner_cancels_cooperatively(qtbot):
    runner = JobRunner()

    def operation(token, _report):
        token.raise_if_cancelled()

    with qtbot.waitSignals([runner.cancelled, runner.finished], timeout=2_000):
        runner.start(operation)
        runner.cancel()

    assert not runner.running
