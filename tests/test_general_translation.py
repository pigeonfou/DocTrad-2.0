import json
from pathlib import Path
import httpx
import pymupdf as fitz
import pytest
from doctrad2.domain import Node, Run
from doctrad2.inference import LlamaTranslator
from doctrad2.layout import source_style, placement_box, text_markup
from doctrad2.quality import check_text, numbers, identifiers, measured_values
from doctrad2.text_policy import translation_source, sentence_parts


@pytest.mark.parametrize('source,target', [
    ('Pressure 7 bar', 'Pression 7 bar'),
    ('Range 8 kHz-22 MHz', 'Plage de 8 kHz à 22 MHz'),
    ('FW v4.7.9', 'Micrologiciel version 4.7.9'),
    ('3-axis sensor and 12-pin plug', 'Capteur à 3 axes et fiche à 12 broches'),
    ('AM-107 dBm @ 6 dB', 'AM : -107 dBm à 6 dB'),
    ('Width 14 inches', 'Largeur 14 pouces'),
    ('4-meter cable', 'Câble de 4 mètres'),
    ('Mass 9.2 lbs', 'Masse de 9,2 livres'),
])
def test_general_numeric_equivalents(source, target):
    assert not [f for f in check_text(source, target, 'n') if f.severity == 'critical']


def test_real_dimension_change_detected_in_an_unrelated_example():
    assert measured_values('2 H x 4 W x 6 D in') != measured_values('2 cm x 4 cm x 6 cm')
    assert measured_values('2 H x 4 W x 6 D in') == measured_values('2 pouces x 4 pouces x 6 pouces')
    assert numbers('Supply -24 V') != numbers('Alimentation 24 V')
    assert identifiers('IEC-62368-1') != identifiers('IEC-62368-2')


def test_unexpected_scripts_and_existing_quoted_scripts():
    assert 'unexpected_script' in [f.code for f in check_text('Two outputs', 'Deux sorties 接口', 'n')]
    assert 'unexpected_script' not in [f.code for f in check_text('Label 接口', 'Étiquette 接口', 'n')]


def test_soft_wraps_preserve_hyphens_and_content():
    assert translation_source('The heat-\nresistant cable\noperates at 80 °C.') == 'The heat-resistant cable operates at 80 °C.'
    source = 'Connect the pump. Check the pressure; Close the valve.'
    assert ' '.join(sentence_parts(source)) == source


def test_conditional_retry_is_ranked_by_fidelity_not_a_document_wordlist(settings):
    calls = []
    def handler(request):
        payload = json.loads(request.content) if request.content else {}
        if request.url.path == '/props':
            return httpx.Response(200, json={'model_path': 'translategemma-12b-it.gguf', 'default_generation_settings': {'n_ctx': 4096}})
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'tokens': [2, 8, 16]})
        calls.append(payload)
        return httpx.Response(200, json={'content': 'Pression 90 V 接口' if len(calls) == 1 else 'Pression 9 V', 'tokens_predicted': 5})
    translator = LlamaTranslator(settings, httpx.MockTransport(handler))
    target, provenance = translator.translate('Pressure 9 V')
    assert target == 'Pression 9 V'
    assert len(calls) == 2
    assert provenance['chunks'][0]['selected_attempt'] == 1
    assert calls[1]['temperature'] == .2


def test_styles_do_not_inherit_bullet_red_or_superscript_size():
    node = Node(page=0, id='n', text='> Flow rate 10 m³', bbox=(30, 30, 130, 65), runs=[
        Run(text='> ', bbox=(30, 30, 35, 40), color=0xff0000, size=10),
        Run(text='Flow rate 10 m', bbox=(40, 30, 120, 40), color=0, size=10, flags=16),
        Run(text='3', bbox=(120, 30, 125, 35), color=0, size=5)])
    assert source_style(node) == (10, 0, 16)
    markup, css = text_markup(node, '> Débit 10 m³')
    assert 'color:#000000' in css and 'font-weight:bold' in css
    assert 'color:#ff0000' in markup


def test_growth_respects_columns_images_and_separators():
    doc = fitz.open()
    page = doc.new_page(width=500, height=600)
    page.draw_line((20, 100), (230, 100))
    node = Node(page=0, id='left', text='Pump instructions', bbox=(30, 50, 200, 90))
    right = Node(page=0, id='right', text='Valve settings', bbox=(260, 50, 450, 140))
    box = placement_box(node, page, [node, right])
    assert box.x1 <= 255  # retain a gutter, never enter the neighboring column
    assert box.y1 < 100


def test_production_policy_has_no_reference_document_dependencies():
    root = Path(__file__).resolve().parents[1] / 'src/doctrad2'
    for name in ('text_policy.py', 'quality.py', 'layout.py', 'inference.py'):
        source = (root / name).read_text()
        assert 'AN/PRC' not in source
        assert 'L3Harris' not in source
        assert 'TOP SECRET' not in source
        assert 'CONFIDENTIEL' not in source


def test_phantom_table_column_does_not_clip_an_independent_label(monkeypatch):
    from types import SimpleNamespace
    from doctrad2.extraction import extract
    doc = fitz.open()
    page = doc.new_page(width=500, height=600)
    page.insert_text((35, 90), 'Emergency pressure limit', fontsize=10)
    page.insert_text((260, 90), '7 bar', fontsize=10)
    table = SimpleNamespace(bbox=(25, 60, 450, 120), row_count=1,
                            rows=[SimpleNamespace(cells=[(25, 60, 100, 120), (100, 60, 240, 120), (240, 60, 450, 120)])])
    monkeypatch.setattr(fitz.Page, 'find_tables', lambda page: SimpleNamespace(tables=[table]))
    ir = extract(doc.tobytes(), 'pdf')
    label = next(n for n in ir.nodes if n.text == 'Emergency pressure limit')
    assert fitz.Rect(label.locator['cell_bbox']).contains(fitz.Rect(label.bbox))
    assert label.locator['cell_bbox'][2] == 240


def test_emphasized_terms_use_source_derived_official_conversation_examples(settings):
    prompts = []
    def handler(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.path == '/props':
            return httpx.Response(200, json={'model_path': 'translategemma-12b-it.gguf', 'default_generation_settings': {'n_ctx': 4096}})
        if request.url.path == '/tokenize':
            prompts.append(body['content'])
            return httpx.Response(200, json={'tokens': [1, 2]})
        return httpx.Response(200, json={'content': 'HAUTE TENSION' if len(prompts) == 1 else 'Attention à la HAUTE TENSION.'})
    translator = LlamaTranslator(settings, httpx.MockTransport(handler))
    target, provenance = translator.translate('Beware of HIGH VOLTAGE.')
    assert 'HAUTE TENSION' in target
    assert provenance['terminology_examples'] == [('HIGH VOLTAGE', 'HAUTE TENSION')]
    assert any(__import__('re').search(r'<start_of_turn>model\s+HAUTE TENSION<end_of_turn>', p) for p in prompts)
    assert all('Beware of HIGH VOLTAGE.' not in p or 'professional English' in p for p in prompts)


def test_unit_restoration_is_source_backed_and_refuses_ambiguity_or_conversion():
    from doctrad2.fidelity import restore_unambiguous_units
    target, repairs = restore_unambiguous_units('Dimensions 2 H x 4 W x 6 D in', 'Dimensions 2 cm x 4 cm x 6 cm')
    assert target == 'Dimensions 2 in x 4 in x 6 in'
    assert len(repairs) == 3
    assert restore_unambiguous_units('Length 1000 m', 'Longueur 1 km') == ('Longueur 1 km', [])
    assert restore_unambiguous_units('Input 12 V and output 12 A', 'Entrée 12 A et sortie 12 V') == ('Entrée 12 A et sortie 12 V', [])
    assert restore_unambiguous_units('Pressure 8 Pa', 'Pression 9 A') == ('Pression 9 A', [])


@pytest.mark.parametrize('angle', [12, 45, 315])
def test_nonorthogonal_vector_text_is_translated_without_flattening(angle):
    from doctrad2.extraction import extract
    from doctrad2.reconstruction import build
    doc = fitz.open()
    page = doc.new_page(width=500, height=600)
    page.insert_text((200, 300), 'Safety tested', fontsize=14, morph=(fitz.Point(200, 300), fitz.Matrix(angle)))
    source = doc.tobytes()
    ir = extract(source, 'pdf')
    assert ir.nodes[0].translatable
    result, report = build(source, ir, {ir.nodes[0].id: 'Sécurité testée'})
    assert not report.blocked, report.findings
    with fitz.open(stream=result, filetype='pdf') as output:
        text = output[0].get_text()
        assert 'Safety' not in text
        assert 'curité' in text
        assert not output[0].get_images()


def test_opaque_spans_are_derived_from_arbitrary_source_and_validate_all_markers():
    from doctrad2.literals import shield, restore, literal_only
    source = 'Use 48 V with 6 A; size 3 H x 5 W x 9 D in; see https://example.net/help.'
    masked, mapping = shield(source)
    assert '48 V' not in masked and '3 H' not in masked and 'https://' not in masked
    assert restore(masked, mapping) == source
    assert restore(masked.replace(next(iter(mapping)), 'unknown'), mapping) is None
    assert restore(masked + masked, mapping) is None
    assert literal_only('https://example.net/help')
    assert literal_only('48 V - 6 A')
    assert not literal_only('Version 8.2 in development')
    assert not [f for f in check_text('Version 8.2 in development', 'Version 8.2 en développement', 'n') if f.code == 'value_units']


def test_failed_numeric_candidates_use_a_bounded_literal_retry(settings):
    import re
    latest = ''
    completions = []
    def handler(request):
        nonlocal latest
        payload = json.loads(request.content) if request.content else {}
        if request.url.path == '/props':
            return httpx.Response(200, json={'model_path': 'translategemma-12b-it.gguf', 'default_generation_settings': {'n_ctx': 4096}})
        if request.url.path == '/tokenize':
            latest = payload['content']
            return httpx.Response(200, json={'tokens': [1, 2]})
        completions.append(latest)
        markers = re.findall(r'<x id="[^"]+"/>', latest)
        content = 'Dimensions : ' + ' '.join(markers) if markers else 'Dimensions : 5 cm x 10 cm x 15 cm.'
        return httpx.Response(200, json={'content': content})
    translator = LlamaTranslator(settings, httpx.MockTransport(handler))
    target, provenance = translator.translate('Dimensions: 2 H x 4 W x 6 D in.')
    assert '2 H x 4 W x 6 D in' in target
    assert '5 cm' not in target
    assert len(completions) == 3
    assert provenance['chunks'][0]['selected_attempt'] == 2
