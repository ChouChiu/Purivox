from __future__ import annotations

import time
from threading import Event

import pytest

from shared.processing import ProgressEvent
from shared.tasks import TaskRunner


def test_task_runner_reports_progress_and_releases_thread(qtbot):
    runner = TaskRunner()
    progress: list[tuple[int, str]] = []
    results: list[object] = []
    runner.progress.connect(lambda value, message: progress.append((value, message)))
    runner.succeeded.connect(results.append)

    def operation(_token, report):
        report(ProgressEvent(42, "working"))
        return ("done",)

    with qtbot.waitSignals([runner.succeeded, runner.finished], timeout=2_000):
        runner.start(operation)
        assert runner.running

    assert progress == [(42, "working")]
    assert results == [("done",)]
    assert not runner.running


def test_task_runner_cancels_cooperatively(qtbot):
    runner = TaskRunner()
    started = Event()
    results: list[object] = []
    runner.succeeded.connect(results.append)

    def operation(token, _report):
        started.set()
        while not token.cancelled:
            time.sleep(0.001)
        token.raise_if_cancelled()

    with qtbot.waitSignals([runner.cancelled, runner.finished], timeout=2_000):
        runner.start(operation)
        assert started.wait(2)
        runner.cancel()

    assert results == []
    assert not runner.running


@pytest.mark.parametrize("error", [ValueError("expected"), KeyError("fault")])
def test_task_runner_reports_expected_and_unexpected_failures_alike(qtbot, error):
    runner = TaskRunner(expected=(ValueError,))
    failures: list[str] = []
    runner.failed.connect(failures.append)

    def operation(_token, _report):
        raise error

    with qtbot.waitSignals([runner.failed, runner.finished], timeout=2_000):
        runner.start(operation)

    assert failures == [str(error)]


def test_task_runner_refuses_a_second_operation_while_one_runs(qtbot):
    runner = TaskRunner()
    with qtbot.waitSignal(runner.finished, timeout=2_000):
        runner.start(lambda _token, _report: None)
        with pytest.raises(RuntimeError):
            runner.start(lambda _token, _report: None)
