"""Bound model-only network work; never detach a tool with local side effects.

Callbacks run on the calling thread. A cancelled worker cannot publish late
tokens or invoke a tool. Slots remain occupied until transport cleanup finishes.
"""

from __future__ import annotations

import contextlib
import queue
import socket
import threading
import time
from contextvars import ContextVar, copy_context

from .tasks import TaskCancelled, checkpoint

_slots = threading.BoundedSemaphore(8)
_transport = ContextVar("studyui_model_transport", default=None)


def transport_checkpoint():
    checkpoint()
    state = _transport.get()
    if state is not None and (state["stop"].is_set() or time.monotonic() >= state["deadline"]):
        raise TaskCancelled("Model transport stopped")


def register_response(response):
    state = _transport.get()
    if state is None:
        return
    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    with state["lock"]:
        state["socket"] = sock
        if state["stop"].is_set() and sock is not None:
            _shutdown(sock)
    transport_checkpoint()


def _shutdown(sock):
    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)


def run_model_io(operation, on_chunk, seconds):
    deadline = time.monotonic() + seconds
    stop = threading.Event()
    events = queue.Queue(maxsize=64)
    state = {"lock": threading.Lock(), "socket": None, "stop": stop, "deadline": deadline}

    def check():
        checkpoint()
        if time.monotonic() >= deadline:
            raise TimeoutError("模型响应超过总时间预算；本次请求已停止，可重试或选择其他模型。")

    while not _slots.acquire(timeout=0.05):
        check()

    def put(kind, value):
        while not stop.is_set():
            try:
                events.put((kind, value), timeout=0.05)
                return
            except queue.Full:
                continue
        raise TaskCancelled("Model request abandoned")

    def worker():
        token = _transport.set(state)
        try:
            value = operation(lambda kind, delta: put("chunk", (kind, delta)))
            put("result", value)
        except BaseException as exc:
            if not stop.is_set():
                put("error", exc)
        finally:
            _transport.reset(token)
            _slots.release()

    context = copy_context()
    try:
        thread = threading.Thread(target=context.run, args=(worker,), daemon=True, name="studyui-model-io")
        thread.start()
    except BaseException:
        _slots.release()
        raise
    try:
        while True:
            check()
            try:
                kind, value = events.get(timeout=0.05)
            except queue.Empty:
                continue
            check()
            if kind == "error":
                raise value
            if kind == "result":
                return value
            if on_chunk:
                on_chunk(*value)
    finally:
        stop.set()
        with state["lock"]:
            if state["socket"] is not None:
                _shutdown(state["socket"])
