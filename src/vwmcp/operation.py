"""Serialize complete tool operations across MCP processes on this Mac."""
from __future__ import annotations
import contextlib
import contextvars
import functools
import os
import threading
import time
from pathlib import Path

writing = contextvars.ContextVar('vwmcp_writing', default=False)
_state = threading.local()
_mutex = threading.RLock()

@contextlib.contextmanager
def exclusive(root: Path, timeout: float = 60):
    # The desktop bridge targets macOS. Never silently proceed without a lock.
    import fcntl
    with _mutex:
        if getattr(_state, 'depth', 0):
            _state.depth += 1
            try:
                yield
            finally:
                _state.depth -= 1
            return
        root.mkdir(parents=True, exist_ok=True)
        with (root / 'operation.lock').open('a') as lock:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('bridge_busy: another client owns the Vectorworks operation')
                    time.sleep(.05)
            _state.depth = 1
            try:
                # A timed-out claimed job may still be modifying the document.
                if list((root / 'jobs').glob('*.running')):
                    raise RuntimeError('operation_unknown: an earlier job is unfinished; inspect it before continuing')
                yield
            finally:
                _state.depth = 0
                fcntl.flock(lock, fcntl.LOCK_UN)

def operation(write=False):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            from vwmcp import app
            from mcp.server.mcpserver.exceptions import ToolError
            b = app.get_bridge()
            try:
                with exclusive(b.root, b.timeout):
                    effective_write = write
                    if fn.__name__ == 'vw_exec_python':
                        import inspect
                        supplied = inspect.signature(fn).bind(*args, **kwargs)
                        effective_write = supplied.arguments.get('modifies_document', True)
                    if effective_write and not b.bound_document:
                        raise RuntimeError('document_not_bound: call vw_bind_document with the full project path before writing')
                    token = writing.set(effective_write)
                    try:
                        return fn(*args, **kwargs)
                    finally:
                        writing.reset(token)
            except RuntimeError as e:
                raise ToolError(str(e)) from e
        return wrapped
    return decorate
