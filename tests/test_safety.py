import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace

import pytest
import vwmcp_bridge
from mcp.server.mcpserver.exceptions import ToolError
from vwmcp import app
from vwmcp.client import Bridge
from vwmcp.operation import exclusive, operation, writing
from vwmcp.tools import generic


def try_lock(root, output):
    try:
        with exclusive(Path(root), .15):
            output.put('acquired')
    except RuntimeError as e:
        output.put(str(e))


def test_process_lock_serializes_clients(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    out = ctx.Queue()
    with exclusive(tmp_path):
        p = ctx.Process(target=try_lock, args=(str(tmp_path), out))
        p.start()
        assert 'bridge_busy' in out.get(timeout=10)
        p.join(5)
        assert p.exitcode == 0
    with exclusive(tmp_path):
        pass


def test_unfinished_job_blocks_new_work(tmp_path):
    (tmp_path / 'jobs').mkdir()
    (tmp_path / 'jobs' / 'old.running').write_text('{}')
    with pytest.raises(RuntimeError, match='operation_unknown'):
        with exclusive(tmp_path):
            pytest.fail('must not enter')


@pytest.mark.parametrize('actual,allowed,error', [
    ('/projects/B.vwx', '/projects', 'wrong_document'),
    ('/projects/A.vwx', '/elsewhere', 'project_outside_allowed_root'),
])
def test_guard_rejects_before_executing(tmp_path, actual, allowed, error):
    jobs = tmp_path / 'jobs'; jobs.mkdir()
    job = {'protocol_version': 2, 'code': 'vs.calls.append("WRITE")', 'expected_document': '/projects/A.vwx', 'allowed_root': allowed}
    (jobs / 'one.json').write_text(json.dumps(job))
    vs = SimpleNamespace(GetFPathName=lambda: actual, calls=[])
    vwmcp_bridge.run_pending(tmp_path, vs_module=vs)
    res = json.loads((tmp_path / 'results/one.json').read_text())
    assert not res['ok'] and error in res['error']
    assert vs.calls == []


def test_successful_guard_and_job_metadata(tmp_path):
    vs = SimpleNamespace(GetFPathName=lambda: '/projects/A.vwx', calls=[])
    b = Bridge(root=tmp_path, trigger=lambda: vwmcp_bridge.run_pending(tmp_path, vs_module=vs))
    b.bound_document = '/projects/A.vwx'
    token = writing.set(True)
    try:
        res = b.run('vs.calls.append("WRITE")')
    finally:
        writing.reset(token)
    assert res['ok'] and vs.calls == ['WRITE']


def test_unbound_client_cannot_write(tmp_path, monkeypatch):
    b = Bridge(root=tmp_path, trigger=lambda: pytest.fail('must not trigger'))
    monkeypatch.setattr(app, 'get_bridge', lambda: b)
    with pytest.raises(ToolError, match='document_not_bound'):
        generic.vw_exec_python('vs.Rect(0,0,1,1)')


def test_binding_rejects_wrong_path_and_old_bridge(tmp_path, monkeypatch):
    b = Bridge(root=tmp_path, trigger=lambda: None)
    monkeypatch.setattr(app, 'get_bridge', lambda: b)
    monkeypatch.setattr(b, 'run', lambda code: {'bridge_version': app.EXPECTED_BRIDGE_VERSION})
    monkeypatch.setattr(generic, 'vw', lambda *a: {'path': '/projects/A.vwx'})
    with pytest.raises(ToolError, match='wrong_document'):
        generic.vw_bind_document('/projects/B.vwx')
    assert b.bound_document is None
    assert generic.vw_bind_document('/projects/A.vwx')['write_guard']
    monkeypatch.setattr(b, 'run', lambda code: {'bridge_version': '0.1.0'})
    with pytest.raises(ToolError, match='bridge_version_mismatch'):
        generic.vw_bind_document('/projects/A.vwx')


def test_allowed_root_rejects_binding_before_cad(tmp_path, monkeypatch):
    b = Bridge(root=tmp_path, trigger=lambda: pytest.fail('must not trigger'))
    monkeypatch.setattr(app, 'get_bridge', lambda: b)
    monkeypatch.setenv('VWMCP_ALLOWED_PROJECT_ROOT', '/projects')
    with pytest.raises(ToolError, match='project_outside_allowed_root'):
        generic.vw_bind_document('/other/Plot.vwx')


def test_doctor_available_while_unfinished(tmp_path, monkeypatch):
    from vwmcp import trigger
    b = Bridge(root=tmp_path, trigger=lambda: pytest.fail('must not trigger'))
    b.jobs.mkdir(); (b.jobs / 'unfinished.running').write_text('{}')
    monkeypatch.setattr(app, 'get_bridge', lambda: b)
    monkeypatch.setattr(trigger, 'mac_app_uptime', lambda app: None)
    assert generic.vw_doctor()['unfinished_jobs'] == ['unfinished']


def test_same_filename_has_separate_journal_history(tmp_path):
    from vwmcp.journal import Journal
    j = Journal(tmp_path / 'journal.jsonl')
    j.record('/a/Plot.vwx', 'insert', [{'uuid': 'one'}])
    j.record('/b/Plot.vwx', 'insert', [{'uuid': 'two'}])
    assert j.pop('/a/Plot.vwx')['ops'] == [{'uuid': 'one'}]
    assert j.pop('/b/Plot.vwx')['ops'] == [{'uuid': 'two'}]


def test_old_client_cannot_execute_code(tmp_path):
    jobs = tmp_path / 'jobs'; jobs.mkdir()
    (jobs / 'old.json').write_text(json.dumps({'code': 'vs.calls.append("WRITE")'}))
    vs = SimpleNamespace(calls=[])
    vwmcp_bridge.run_pending(tmp_path, vs_module=vs)
    result = json.loads((tmp_path / 'results/old.json').read_text())
    assert 'incompatible_client' in result['error'] and not vs.calls
