import sys
import threading
import time

import pytest

from pcb_assistant.cancellation import cancel_event, check_cancelled, JobCancelled, run_process
from pcb_assistant.orchestrator import Orchestrator
from pcb_assistant.schemas import PartsDiscovery, PartCandidate
from pcb_assistant.web_research import acquire_sources


def wait_terminal(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get('/api/jobs/' + job_id).json()
        if result['status'] not in ('queued', 'running'):
            return result
        time.sleep(.01)
    pytest.fail('Job failed to terminate')


def test_cancel_saves_completed_work_and_allows_resume(client, valid_project, monkeypatch):
    p = client.app.state.store.save(valid_project, 0, 'fixture')
    entered = threading.Event()
    def slow_plan(self, project):
        project.pipeline_cache['completed-test-stage'] = 'retained'
        entered.set()
        while True:
            check_cancelled()
            time.sleep(.01)
    monkeypatch.setattr(Orchestrator, 'plan', slow_plan)
    endpoint = '/api/projects/' + p.id
    job = client.post(endpoint + '/jobs', json={'version': p.version, 'reason': 'test', 'stage': 'plan'}).json()
    assert entered.wait(3)
    assert client.get('/api/jobs').json()[0]['id'] == job['id']
    assert client.post(endpoint + '/jobs', json={'version': p.version, 'reason': 'duplicate', 'stage': 'plan'}).status_code == 400
    assert client.put(endpoint + '/requirements', json={'version': p.version, 'reason': 'race', 'values': p.requirements.values.model_dump()}).status_code == 400
    assert client.post('/api/jobs/' + job['id'] + '/cancel').status_code == 200
    assert wait_terminal(client, job['id'])['status'] == 'cancelled'
    saved = client.get(endpoint).json()['project']
    assert saved['pipeline_cache']['completed-test-stage'] == 'retained'
    assert saved['circuit'] == p.circuit.model_dump(mode='json')
    assert client.get('/api/jobs').json() == []
    monkeypatch.setattr(Orchestrator, 'plan', lambda self, project: None)
    retry = client.post(endpoint + '/jobs', json={'version': saved['version'], 'reason': 'resume', 'stage': 'plan'}).json()
    assert wait_terminal(client, retry['id'])['status'] == 'done'


def test_identical_part_selection_does_not_destroy_evidence(client, valid_project):
    valid_project.discovery = PartsDiscovery(parts=[PartCandidate(ref='U1', part_number='TEST', manufacturer='TEST',
        role='test', package='TEST', rationale='fixture', status='selected', product_url='', datasheet_url='')])
    p = client.app.state.store.save(valid_project, 0, 'fixture')
    result = client.post('/api/projects/' + p.id + '/parts/decide', json={
        'version': p.version, 'reason': 'same selection', 'refs': ['U1'], 'accept': True}).json()['project']
    assert result == p.model_dump(mode='json')


def test_failed_download_is_not_repeated_until_explicit_retry(valid_project, monkeypatch):
    valid_project.sources = []
    valid_project.discovery = PartsDiscovery(parts=[PartCandidate(ref='U1', part_number='TEST', manufacturer='TEST',
        role='test', package='TEST', rationale='fixture', status='selected', product_url='', datasheet_url='https://example.com/fail.pdf')])
    calls = []
    def fail(url):
        calls.append(url)
        raise ValueError('HTTP 404')
    monkeypatch.setattr('pcb_assistant.web_research.fetch_pdf', fail)
    assert acquire_sources(valid_project, None)
    assert acquire_sources(valid_project, None)
    assert len(calls) == 1
    valid_project.pipeline_cache = {}
    assert acquire_sources(valid_project, None)
    assert len(calls) == 2


def test_cancellation_terminates_only_owned_child():
    event = threading.Event()
    scope = cancel_event.set(event)
    timer = threading.Timer(.3, event.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(JobCancelled):
            run_process([sys.executable, '-c', 'import time; time.sleep(30)'], input='', timeout=10, text=True)
        assert time.monotonic() - started < 5
    finally:
        timer.cancel()
        cancel_event.reset(scope)


def test_requirements_job_uses_cancellable_worker(client, requirement):
    p = client.post('/api/projects', json={'name': 'Fixture', 'brief': 'Synthetic only'}).json()['project']
    job = client.post('/api/projects/' + p['id'] + '/jobs', json={
        'version': p['version'], 'reason': 'test', 'stage': 'requirements',
        'requirements': {'version': p['version'], 'reason': 'test', 'values': requirement.model_dump()}}).json()
    result = wait_terminal(client, job['id'])
    assert result['status'] == 'done'
    assert result['result']['project']['requirements']['values']['mcu'] == 'TEST-MCU'
