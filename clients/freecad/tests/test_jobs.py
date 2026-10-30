"""Concurrency and failure tests for the GUI-independent workflow engine."""

from threading import Event, get_ident
import time

from freecad.forgepdm.jobs import OperationCancelled, Request, WorkflowJob


def finish(job):
    deadline = time.monotonic() + 3
    while not job.done and time.monotonic() < deadline:
        job.poll()
        time.sleep(0.001)
    assert job.done


def test_io_runs_in_worker_and_continuation_on_calling_thread():
    main = get_ident()
    threads = []
    release = Event()

    def io():
        threads.append(get_ident())
        assert release.wait(2)
        return 42

    def workflow():
        threads.append(get_ident())
        result = yield Request("Read", io)
        assert result == 42
        threads.append(get_ident())

    job = WorkflowJob(workflow())
    job.start()
    assert not job.done
    # Polling does not wait for the network operation.
    job.poll()
    assert not job.done
    release.set()
    finish(job)
    assert job.error is None
    assert threads[0] == threads[-1] == main
    assert threads[1] != main


def test_cancel_does_not_run_followup_or_replay_mutation():
    started, release = Event(), Event()
    calls = []

    def write():
        calls.append("write")
        started.set()
        assert release.wait(2)

    def workflow():
        yield Request("Upload", write, mutates=True)
        calls.append("checkin")

    job = WorkflowJob(workflow())
    job.start()
    assert started.wait(2)
    assert job.cancel()
    release.set()
    finish(job)
    assert calls == ["write"]
    assert isinstance(job.error, OperationCancelled)
    assert job.may_have_changed_server


def test_uncancellable_finalization_finishes_before_next_operation():
    release = Event()

    def workflow():
        yield Request("Finalize", lambda: release.wait(2), mutates=True, cancellable=False)

    job = WorkflowJob(workflow())
    job.start()
    assert job.cancel() is False
    release.set()
    finish(job)
    assert job.error is None


def test_request_error_is_delivered_to_workflow_without_automatic_retry():
    calls = []

    def fail():
        calls.append(1)
        raise TimeoutError("timeout")

    def workflow():
        yield Request("Read", fail)

    job = WorkflowJob(workflow())
    job.start()
    finish(job)
    assert isinstance(job.error, TimeoutError)
    assert calls == [1]


def test_nested_event_loop_cannot_reenter_generator():
    def workflow():
        yield Request("Read", lambda: 1)
        # Qt dialogs can run a nested event loop while a continuation runs.
        job.poll()

    job = WorkflowJob(workflow())
    job.start()
    finish(job)
    assert job.error is None


def test_request_diagnostics_do_not_include_credentials():
    request = Request(
        "Login", lambda: None, ("alice", "secret-password"), {"token": "secret-token"}
    )
    assert "secret-password" not in repr(request)
    assert "secret-token" not in repr(request)
