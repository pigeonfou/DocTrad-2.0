import hashlib
import json

import httpx
import pymupdf as fitz
import pytest

from doctrad2.skynet_cli import export
from doctrad2.skynet_document import import_document, translation_plan
from doctrad2.skynet_inference import Endpoint, InferenceConfig, InferenceDisabled, ModelAPI
from doctrad2.skynet_store import DocumentStore, RevisionConflict
from doctrad2.domain import Node


@pytest.fixture
def document(tmp_path):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((40, 60), 'Input voltage: 12 V.', fontsize=11)
    page.insert_text((40, 140), 'Current: 3.5 A.', fontsize=11)
    page.draw_rect(fitz.Rect(300, 200, 420, 280), color=(1, 0, 0), fill=(1, 0, 0))
    source = tmp_path / 'source.pdf'
    pdf.save(source)
    pdf.close()
    store = DocumentStore(tmp_path / 'store')
    digest = import_document(store, source)
    return store, digest, source


def test_import_retains_original_geometry_preview_and_no_inference(document):
    store, digest, source = document
    snapshot, ir = store.document(digest)
    assert store.read(snapshot['original']) == source.read_bytes()
    assert ir.source_sha == hashlib.sha256(source.read_bytes()).hexdigest()
    assert len(ir.nodes) == 2 and all(node.bbox for node in ir.nodes)
    assert store.read(snapshot['page_assets'][0]['object']).startswith(b'\x89PNG')
    assert not snapshot['remote_inference_performed']
    plan = translation_plan(store, digest)
    assert {unit['block_id'] for unit in plan['units']} == {node.id for node in ir.nodes}
    assert all(unit['needs_exact_tokenization'] for unit in plan['units'])


def test_revisions_are_incremental_immutable_and_conflict_checked(document):
    store, digest, source = document
    _, ir = store.document(digest)
    a, b = [node.id for node in ir.nodes]
    first = store.revise(digest, None, {a: "Tension d'entrée : 12 V."}, 'tester', 'First block')
    original_revision = store.read(first)
    second = store.revise(digest, first, {b: 'Courant : 3,5 A.'}, 'tester', 'Second block')
    assert store.read(first) == original_revision
    assert store.read_json(second)['entries'][a] == store.read_json(first)['entries'][a]
    assert store.read_json(second)['parent'] == first
    with pytest.raises(RevisionConflict):
        store.revise(digest, first, {a: '12 V'}, 'tester', 'Stale edit')
    assert store.head(digest) == second
    assert store.read(ir.source_sha) == source.read_bytes()
    with pytest.raises(ValueError, match='unknown_source_block'):
        store.revise(digest, second, {'invented': '12 V'}, 'tester', 'Invalid patch')


def test_corruption_and_path_escape_are_rejected(document):
    store, digest, _ = document
    with pytest.raises(ValueError, match='invalid_object_digest'):
        store.read('../secrets')
    store.object_path(digest).write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='object_digest_mismatch'):
        store.document(digest)


def test_table_context_uses_current_row_header_not_unrelated_rows(document):
    store, digest, _ = document
    snapshot, ir = store.document(digest)
    ir.nodes = [Node(id=block_id, page=0, text=text, parent='table-1', kind='table_cell',
                     locator={'row': row, 'column': column}) for block_id, text, row, column in [
        ('column-header', 'Value', 0, 1), ('voltage-label', 'Input voltage', 1, 0),
        ('voltage-value', '12 V', 1, 1), ('current-label', 'Current', 2, 0),
        ('current-value', '3.5 A', 2, 1)]]
    snapshot['ir'] = ir.model_dump()
    plan = translation_plan(store, store.put_json(snapshot))
    voltage = next(item for item in plan['units'] if item['block_id'] == 'voltage-value')
    assert {item['block_id'] for item in voltage['context']['table_headers']} == {
        'column-header', 'voltage-label'}


def test_critical_unit_change_blocks_export_without_overwriting_source(document, tmp_path):
    store, digest, source = document
    before = source.read_bytes()
    _, ir = store.document(digest)
    revision = store.revise(digest, None, {ir.nodes[0].id: 'Tension : 12 A.',
                                          ir.nodes[1].id: 'Courant : 3,5 A.'}, 'tester', 'Bad units')
    output = tmp_path / 'target.pdf'
    with pytest.raises(ValueError, match='critical_findings'):
        export(store, digest, revision, output)
    assert not output.exists() and source.read_bytes() == before
    # Even a stored report with its critical findings removed must be rechecked.
    forged = store.read_json(revision)
    for item in forged['entries'].values():
        item['findings'] = []
    forged_revision = store.put_json(forged)
    with pytest.raises(ValueError, match='critical_findings'):
        export(store, digest, forged_revision, output)


def test_complete_native_export_is_a_reviewable_baseline(document, tmp_path):
    store, digest, source = document
    _, ir = store.document(digest)
    revision = store.revise(digest, None, {ir.nodes[0].id: "Tension d'entrée : 12 V.",
                                          ir.nodes[1].id: 'Courant : 3,5 A.'}, 'tester', 'Native render')
    output = tmp_path / 'target.pdf'
    proof = export(store, digest, revision, output)
    assert proof['requires_review']
    assert store.read(proof['artifact']) == output.read_bytes()
    with fitz.open(output) as target, fitz.open(source) as original:
        assert len(target) == len(original)
        assert '12 V' in target[0].get_text()
        assert target[0].get_pixmap(clip=fitz.Rect(300, 200, 420, 280)).samples == original[0].get_pixmap(
            clip=fitz.Rect(300, 200, 420, 280)).samples
    with pytest.raises(FileExistsError):
        export(store, digest, revision, output)


def config(role='translation', enabled=True):
    return InferenceConfig(remote_enabled=enabled, endpoints=(Endpoint(
        role=role, base_url='https://192.168.6.44:18081/v1', model_id='test-model', repository='test/model',
        artifact_sha256='a' * 64, engine_sha256='b' * 64, projector_sha256='c' * 64,
        api_key_env='DOCTRAD_SKYNET_TEST_KEY', max_output_tokens=64, context_tokens=1024),))


def transport(result, calls, finish='stop', model='test-model', token_count=8):
    def handle(request):
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path == '/apply-template':
            return httpx.Response(200, json={'prompt': 'rendered by runtime'})
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'tokens': list(range(token_count))})
        return httpx.Response(200, json={'model': model, 'choices': [
            {'finish_reason': finish, 'message': {'content': json.dumps(result)}}]})
    return httpx.MockTransport(handle)


def test_disabled_connection_cannot_create_a_network_client(monkeypatch):
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: pytest.fail('Network client must not be created'))
    with pytest.raises(InferenceDisabled):
        ModelAPI(config(enabled=False), 'translation')
    assert not config(enabled=False).readiness()['network_contacted']


@pytest.mark.parametrize('url', ['http://192.168.6.44:18081/v1', 'https://example.com/v1',
                               'https://192.168.6.44/v1?key=secret', 'https://user:secret@192.168.6.44/v1'])
def test_endpoint_cannot_send_documents_to_another_host(url):
    with pytest.raises(ValueError):
        Endpoint(role='translation', base_url=url, model_id='test', repository='test/model',
                 api_key_env='DOCTRAD_SKYNET_TEST_KEY')


@pytest.mark.parametrize('finish,model,patch,error', [
    ('length', 'test-model', {'block_id': 'n1', 'part': 0, 'target': '12 V'}, 'incomplete'),
    ('stop', 'wrong-model', {'block_id': 'n1', 'part': 0, 'target': '12 V'}, 'unexpected_loaded'),
    ('stop', 'test-model', {'block_id': 'other', 'part': 0, 'target': '12 V'}, 'invalid_translation_patch'),
    ('stop', 'test-model', {'block_id': 'n1', 'part': 0, 'target': '12 V', 'source': 'edited'}, 'invalid_translation_patch'),
])
def test_bad_model_results_cannot_be_applied(monkeypatch, finish, model, patch, error):
    monkeypatch.setenv('DOCTRAD_SKYNET_TEST_KEY', 'fixture-secret')
    calls = []
    client = ModelAPI(config(), 'translation', transport(patch, calls, finish, model))
    try:
        with pytest.raises(ValueError, match=error):
            client.translate_unit({'block_id': 'n1', 'part': 0, 'source': '12 V'})
    finally:
        client.close()


def test_exact_token_budget_checked_before_generation(monkeypatch):
    monkeypatch.setenv('DOCTRAD_SKYNET_TEST_KEY', 'fixture-secret')
    calls = []
    client = ModelAPI(config(), 'translation', transport({}, calls, token_count=1000))
    try:
        with pytest.raises(ValueError, match='context_budget'):
            client.translate_unit({'block_id': 'n1', 'part': 0, 'source': '12 V'})
        assert [path for path, _ in calls] == ['/apply-template', '/tokenize']
    finally:
        client.close()


def test_valid_translation_and_ephemeral_image_payload(monkeypatch):
    monkeypatch.setenv('DOCTRAD_SKYNET_TEST_KEY', 'fixture-secret')
    calls = []
    client = ModelAPI(config(), 'translation', transport({'block_id': 'n1', 'part': 0, 'target': 'Tension : 12 V'}, calls))
    try:
        assert client.translate_unit({'block_id': 'n1', 'part': 0, 'source': 'Input: 12 V'}) == 'Tension : 12 V'
    finally:
        client.close()
    calls = []
    client = ModelAPI(config(role='vision'), 'vision', transport({'region_id': 'r1', 'text': '', 'uncertain': True}, calls))
    try:
        assert client.read_region(b'\x89PNG\r\n\x1a\nfixture', 'r1')['uncertain']
        assert calls[0][1]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
        assert 'fixture-secret' not in json.dumps(config().model_dump())
    finally:
        client.close()
