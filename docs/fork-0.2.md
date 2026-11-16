# Mac fork 0.2

Writes now require `vw_bind_document(path)` in each MCP client session. The
path must be an absolute saved `.vwx` path matching the active document.
The bridge checks this path again immediately before each write job. The
journal uses full paths so equal filenames in different folders stay separate.

Set `VWMCP_ALLOWED_PROJECT_ROOT` in the MCP environment to a project directory;
files outside it cannot be bound for writing. This is a configurable workflow
guard for trusted clients, not a sandbox for arbitrary Python.

All tools except `vw_doctor` acquire a macOS interprocess lock for the entire
operation, including verification and journaling. An unfinished `.running`
job blocks further calls, even after a client timeout. `vw_doctor` can still
report these jobs. Never delete a running marker or repeat a write until the
previous operation's outcome has been inspected. This release does not yet
provide automatic recovery of interrupted writes or full rollback of Python.

`vw_doctor` checks local state without invoking Vectorworks. `vw_ping` checks
the menu command and bridge/server compatibility; binding refuses an older
bridge. Install the matching plugin and reconnect clients when upgrading.
The Python module may be cached by Vectorworks; restart through your usual
launcher after saving documents if the live bridge version remains old.

Development: `uv sync --group dev`, `uv run pytest -q`, `uv build --wheel`.
Test live only on a saved copy in the configured project directory. Keep
production installed from a built wheel, separate from the development tree.
