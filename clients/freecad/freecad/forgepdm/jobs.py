"""GUI-independent workflow engine: only yielded requests run in a worker."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field
from threading import Event, Lock


class OperationCancelled(Exception):
    """A cooperative cancellation stopped subsequent workflow steps."""


class Context:
    def __init__(self):
        self.cancelled = Event()
        self._lock = Lock()
        self._progress = None

    def check(self):
        if self.cancelled.is_set():
            raise OperationCancelled()

    def progress(self, completed, total):
        with self._lock:
            self._progress = (completed, total)

    def latest_progress(self):
        with self._lock:
            return self._progress

    def reset_progress(self):
        with self._lock:
            self._progress = None


@dataclass
class Request:
    label: str
    function: object
    args: tuple = field(default=(), repr=False)
    kwargs: dict = field(default_factory=dict, repr=False)
    mutates: bool = False
    cancellable: bool = True

    @property
    def client(self):
        return getattr(self.function, "__self__", None)

    def execute(self, context):
        context.check()
        owner = self.client
        manager = owner.operation(context) if hasattr(owner, "operation") else nullcontext()
        with manager:
            return self.function(*self.args, **self.kwargs)


class WorkflowJob:
    """Call start/poll on the GUI thread; never call Future.result until done."""

    def __init__(self, workflow, executor=None):
        self.workflow = workflow
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="ForgePDM")
        self._owns_executor = executor is None
        self.context = Context()
        self.request = None
        self.future = None
        self.done = False
        self.error = None
        self.may_have_changed_server = False
        self.completed_mutations = False
        self._advancing = False

    def start(self):
        self._advance()

    def cancel(self):
        if self.request is not None and not self.request.cancellable:
            return False
        self.context.cancelled.set()
        return True

    def poll(self):
        if self.done or self._advancing or self.future is None or not self.future.done():
            return
        try:
            result = self.future.result()
        except BaseException as error:
            if self.context.cancelled.is_set():
                self._finish(OperationCancelled())
            else:
                self._advance(error=error)
        else:
            self.completed_mutations |= self.request.mutates
            if self.context.cancelled.is_set():
                self._finish(OperationCancelled())
            else:
                self._advance(result)

    def _advance(self, value=None, error=None):
        self._advancing = True
        try:
            request = self.workflow.throw(error) if error is not None else self.workflow.send(value)
            if not isinstance(request, Request):
                raise TypeError("Workflows must yield Request instances")
            self.request = request
            self.context.reset_progress()
            self.may_have_changed_server |= request.mutates
            self.future = self.executor.submit(request.execute, self.context)
        except StopIteration:
            self._finish()
        except BaseException as exception:
            self._finish(exception)
        finally:
            self._advancing = False

    def _finish(self, error=None):
        self.done = True
        self.error = error
        try:
            self.workflow.close()
        finally:
            if self._owns_executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
