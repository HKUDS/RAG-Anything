from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile


def _load_suite():
    spec = importlib.util.spec_from_file_location('suite', 'scripts/kb_regression_suite.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_norm_url_appends_api_once():
    suite = _load_suite()
    assert suite.norm_url('http://127.0.0.1:8001') == 'http://127.0.0.1:8001/api'
    assert suite.norm_url('http://127.0.0.1:8001/api') == 'http://127.0.0.1:8001/api'


def test_strip_hash_removes_prefix_only():
    suite = _load_suite()
    assert suite.strip_hash('1a2b3c4d_report.pdf') == 'report.pdf'
    assert suite.strip_hash('report.pdf') == 'report.pdf'


def test_matrix_smoke_and_full_selection():
    suite = _load_suite()
    assert suite.matrix('smoke', [], ['docx', 'pdf']) == [('fixed_size', 'docx'), ('structure', 'pdf')]
    full = suite.matrix('full', ['recursive'], ['pdf'])
    assert full == [('recursive', 'pdf')]


def test_name_allocator_skips_used_names():
    suite = _load_suite()
    allocator = suite.NameAllocator({'test01', 'test02'})
    assert allocator.next() == 'test03'


def test_default_sample_paths_parse_to_expected_suffixes():
    suite = _load_suite()
    assert Path(suite.DEFAULT_DOCX).name.endswith('.docx')
    assert Path(suite.DEFAULT_PDF).name.endswith('.pdf')
    assert Path(suite.DEFAULT_VIDEO).name.endswith('.mp4')


def test_delete_probe_records_delete_request_elapsed_time(monkeypatch, tmp_path):
    suite = _load_suite()
    sample_path = tmp_path / 'report.docx'
    sample_path.write_text('demo', encoding='utf-8')

    class DummyApi:
        def upload_file(self, *_args, **_kwargs):
            return {'task_id': 'task-1'}

        def download_document(self, *_args):
            return type('Response', (), {'status_code': 200, 'headers': {}})(), b'docx'

        def delete_document(self, *_args):
            return {'status': 'deleted'}

    monkeypatch.setattr(suite, 'create_kb_and_agent', lambda *_args: ('test01', {'id': 'agent-1'}))
    monkeypatch.setattr(suite, 'isolated_upload_copy', lambda path: path)
    monkeypatch.setattr(suite, 'cleanup_temp_path', lambda _path: None)
    monkeypatch.setattr(suite, 'wait_for_task', lambda *_args: ({'status': 'completed'}, [], 1.0))
    monkeypatch.setattr(
        suite,
        'wait_for_document_or_placeholder',
        lambda *_args: ({'id': 'doc-1', 'file': 'report.docx'}, [], 0.1, ''),
    )
    monkeypatch.setattr(suite, 'doc_id_of', lambda _doc: 'doc-1')
    monkeypatch.setattr(suite, 'wait_for_absence', lambda *_args: True)
    monotonic_values = iter([10.0, 12.5])
    monkeypatch.setattr(suite.time, 'monotonic', lambda: next(monotonic_values))

    result = suite.run_delete_probe(
        DummyApi(), suite.NameAllocator(set()), suite.create_tracker(),
        {'path': sample_path, 'toggles': {}}, 60.0, 1.0,
    )

    assert result['delete_elapsed_seconds'] == 2.5
    check = next(item for item in result['checks'] if item['name'] == 'delete_response_within_budget')
    assert check['passed'] is True
    assert check['severity'] == 'warning'


def test_isolated_upload_copy_preserves_suffix_and_changes_name(tmp_path, monkeypatch):
    suite = _load_suite()
    source = tmp_path / 'report.docx'
    source.write_text('demo', encoding='utf-8')
    monkeypatch.setattr(suite.tempfile, 'gettempdir', lambda: str(tmp_path / 'temp-root'))

    copied = suite.isolated_upload_copy(source)

    assert copied.exists()
    assert copied.name.endswith('_report.docx')
    assert copied.name != source.name
    assert copied.read_text(encoding='utf-8') == 'demo'


def test_cleanup_temp_path_ignores_missing_file(tmp_path):
    suite = _load_suite()
    missing = tmp_path / 'missing.docx'

    suite.cleanup_temp_path(missing)

    assert missing.exists() is False


def test_api_client_refreshes_token_before_expiry(monkeypatch):
    suite = _load_suite()

    class FakeResponse:
        def __init__(self, status_code, json_data=None, text=''):
            self.status_code = status_code
            self._json = json_data
            self.text = text
            self.content = text.encode('utf-8')
            self.headers = {'content-type': 'application/json'}

        def json(self):
            return self._json

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = {}
            self.requests = []

        def request(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs, dict(self.headers)))
            if path == '/auth/login':
                token = f"token-{len([item for item in self.requests if item[1] == '/auth/login'])}"
                return FakeResponse(200, {'access_token': token})
            return FakeResponse(200, {'ok': True, 'path': path})

        def close(self):
            return None

    monotonic_values = iter([0.0, suite.AUTH_REFRESH_SECONDS + 1.0])
    monkeypatch.setattr(suite.httpx, 'Client', FakeClient)
    monkeypatch.setattr(suite.time, 'monotonic', lambda: next(monotonic_values))

    api = suite.ApiClient('http://127.0.0.1:8001/api', 30.0)
    try:
        api.login('admin', 'secret')
        _, data = api.req('GET', '/kb/list')
    finally:
        api.close()

    assert data['ok'] is True
    login_calls = [item for item in api.client.requests if item[1] == '/auth/login']
    assert len(login_calls) == 2
    assert api.client.headers['Authorization'] == 'Bearer token-2'


def test_api_client_retries_non_file_request_after_401(monkeypatch):
    suite = _load_suite()

    class FakeResponse:
        def __init__(self, status_code, json_data=None, text=''):
            self.status_code = status_code
            self._json = json_data
            self.text = text
            self.content = text.encode('utf-8')
            self.headers = {'content-type': 'application/json'}

        def json(self):
            return self._json

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = {}
            self.calls = []
            self.tasks_calls = 0
            self.login_calls = 0

        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs, dict(self.headers)))
            if path == '/auth/login':
                self.login_calls += 1
                return FakeResponse(200, {'access_token': f'token-{self.login_calls}'})
            if path == '/upload/tasks':
                self.tasks_calls += 1
                if self.tasks_calls == 1:
                    return FakeResponse(401, {'detail': 'Token invalid'})
                return FakeResponse(200, {'tasks': []})
            return FakeResponse(200, {'ok': True})

        def close(self):
            return None

    monkeypatch.setattr(suite.httpx, 'Client', FakeClient)

    api = suite.ApiClient('http://127.0.0.1:8001/api', 30.0)
    try:
        api.login('admin', 'secret')
        _, data = api.req('GET', '/upload/tasks', params={'kb': 'test01'})
    finally:
        api.close()

    assert data == {'tasks': []}
    assert api.client.login_calls == 2
    task_calls = [item for item in api.client.calls if item[1] == '/upload/tasks']
    assert len(task_calls) == 2


def test_finish_marks_environment_failures_as_blocked():
    suite = _load_suite()
    result = {'checks': [suite.make_check('scenario_runtime_error', False, {'error': 'Connection refused'}, severity='error')]}
    finished = suite.finish(result)
    assert finished['status'] == 'blocked'
    assert finished['passed'] is False


def test_finish_keeps_blocked_when_environment_failure_causes_secondary_errors():
    suite = _load_suite()
    result = {
        'checks': [
            suite.make_check('task_completed', False, {'error': 'additional.dat missing in docling'}, severity='error'),
            suite.make_check('chunks_non_empty', False, {'count': 0}, severity='error'),
        ]
    }
    finished = suite.finish(result)
    assert finished['status'] == 'blocked'


def test_group_counts_includes_blocked_results():
    suite = _load_suite()
    counts = suite.group_counts([
        {'status': 'passed', 'checks': []},
        {'status': 'failed', 'checks': []},
        {'status': 'blocked', 'checks': []},
        {'status': 'skipped', 'checks': []},
    ])
    assert counts == {'passed': 1, 'failed': 1, 'blocked': 1, 'skipped': 1, 'warnings': 0, 'total': 4}


def test_multimodal_evidence_detects_inline_media_markers():
    suite = _load_suite()
    report = suite.multimodal_evidence_report(
        [{'content': '[图片]\\n路径: image_0.png', 'is_multimodal': False, 'original_type': None, 'modal_entity_name': None, 'media_path': None, 'media_url': None}],
        {'file_type': 'docx'},
    )
    assert report['found'] is True
    assert report['signals']['content_hint'] == 1


def test_multimodal_evidence_detects_canonical_chunk_template():
    suite = _load_suite()
    report = suite.multimodal_evidence_report(
        [{'content': 'Image Content Analysis:\\nImage Path: image.png'}],
        {'file_type': 'pdf'},
    )
    assert report['found'] is True
    assert report['signals']['content_hint'] == 1


def test_vision_embedding_health_probe_classifies_authorization_block():
    suite = _load_suite()

    class DummyApi:
        def vision_embedding_health(self):
            return {
                'status': 'blocked',
                'available': False,
                'disabled_reason': 'authentication_failed',
                'status_code': 401,
            }

    result = suite.run_vision_embedding_health_probe(DummyApi())

    assert result['status'] == 'passed'
    check = result['checks'][0]
    assert check['name'] == 'vision_embedding_authorized'
    assert check['severity'] == 'warning'
    assert check['classification']['code'] == 'vision_embedding_auth_blocked'


def test_chunk_metadata_report_checks_all_chunks():
    suite = _load_suite()
    good = {
        'chunk_id': 'a',
        'content': 'x',
        'tokens': 1,
        'chunk_order_index': 0,
        'file_path': 'demo.pdf',
        'is_multimodal': False,
        'original_type': None,
        'modal_entity_name': None,
        'page_idx': None,
        'media_path': None,
        'media_url': None,
    }
    bad = dict(good)
    bad.pop('media_url')
    report = suite.chunk_metadata_report([good, bad])
    assert report['complete'] is False
    assert report['issues'][0]['chunk_index'] == 1


def test_read_log_excerpt_decodes_utf16le_log():
    suite = _load_suite()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / 'server.log'
        path.write_text('PermissionError: [WinError 5] 拒绝访问', encoding='utf-16')
        text = suite.read_log_excerpt(path, 0)
    assert 'PermissionError' in text
    assert 'WinError 5' in text


def test_rbac_required_roles_are_canonical_v2():
    suite = _load_suite()
    assert suite.RBAC_REQUIRED_ROLES == ('super_admin', 'dept_admin', 'teacher', 'assistant', 'student')


def test_role_by_name_matches_exact_role_name():
    suite = _load_suite()
    roles = [{'id': 1, 'name': 'student'}, {'id': 2, 'name': 'teacher'}]
    assert suite.role_by_name(roles, 'student')['id'] == 1
    assert suite.role_by_name(roles, 'super_admin') is None


def test_run_rbac_probe_requires_canonical_roles():
    suite = _load_suite()

    class DummyAdminApi:
        def roles(self):
            return {'roles': [{'id': 9, 'name': 'student'}]}

    result = suite.run_rbac_probe(DummyAdminApi(), 'http://127.0.0.1:8001/api', suite.NameAllocator(set()), suite.create_tracker())

    assert result['status'] == 'failed'
    failed_checks = {check['name']: check for check in result['checks'] if not check['passed']}
    assert 'rbac_v2_roles_available' in failed_checks
    assert failed_checks['rbac_v2_roles_available']['details']['missing'] == ['super_admin', 'dept_admin', 'teacher', 'assistant']


def test_run_rbac_probe_uses_five_level_role_catalog(monkeypatch):
    suite = _load_suite()
    created_users = []
    tracker = suite.create_tracker()
    allocator = suite.NameAllocator(set())
    roles = [
        {'id': 1, 'name': 'student'},
        {'id': 2, 'name': 'assistant'},
        {'id': 3, 'name': 'teacher'},
        {'id': 4, 'name': 'dept_admin'},
        {'id': 5, 'name': 'super_admin'},
    ]

    class DummyAdminApi:
        def roles(self):
            return {'roles': roles}

        def create_user(self, username, password, role_id):
            created_users.append((username, role_id))
            return {'user': {'id': len(created_users), 'username': username}}

        def auth_me(self):
            return {'user': {'id': 7, 'username': 'admin', 'is_admin': True}}

        def create_kb(self, name):
            return {'status': 'created', 'name': name, 'label': name}

        def reprocess_multimodal(self, kb_name):
            return {'status': 'queued', 'total': 0}

    class FakeLowApi:
        def __init__(self, base_url, timeout):
            self.base_url = base_url
            self.timeout = timeout
            self.username = None

        def login(self, username, password):
            self.username = username
            return {'status': 'ok'}

        def create_kb(self, name):
            if self.username and self.username.endswith('_student'):
                raise suite.SuiteError('POST /kb/create -> 403: student denied')
            return {'status': 'created', 'name': name, 'label': name}

        def kbs(self):
            if self.username and self.username.endswith('_student'):
                return {'knowledge_bases': [], 'active': 'default'}
            return {'knowledge_bases': [{'name': 'test'}], 'active': 'test'}

        def reprocess_multimodal(self, kb_name, expected=(200,)):
            if self.username and self.username.endswith(('_student', '_teacher')):
                return {'detail': '403 denied'}
            return {'status': 'queued'}

        def close(self):
            return None

    monkeypatch.setattr(suite, 'ApiClient', FakeLowApi)

    result = suite.run_rbac_probe(DummyAdminApi(), 'http://127.0.0.1:8001/api', allocator, tracker)

    assert result['status'] == 'passed'
    assert list(result['matrix']) == ['student', 'teacher', 'super_admin']
    checks = {check['name']: check for check in result['checks']}
    assert checks['student_kb_write_denied']['passed'] is True
    assert checks['student_kb_list_stays_empty']['passed'] is True
    assert checks['student_admin_reprocess_denied']['passed'] is True
    assert checks['teacher_kb_write_allowed']['passed'] is True
    assert checks['teacher_admin_reprocess_denied']['passed'] is True
    assert checks['super_admin_kb_write_allowed']['passed'] is True
    assert checks['super_admin_reprocess_allowed']['passed'] is True
    assert [item[1] for item in created_users] == [1, 3]
