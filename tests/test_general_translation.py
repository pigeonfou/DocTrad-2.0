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
