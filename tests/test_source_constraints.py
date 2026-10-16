import json
import httpx
import pytest
from doctrad2.constraints import french_script_grammar, source_labels
from doctrad2.inference import LlamaTranslator, InferenceError
from doctrad2.quality import check_text, source_unit_spellings
from doctrad2.technical_prompt import render_technical


def test_formal_labels_come_from_source_and_ordinary_headings_still_translate():
    source = 'The installation is approved for operation in CATEGORY FOUR.'
    assert source_labels(source) == ['CATEGORY FOUR']
    assert source_labels('HIGH VOLTAGE INPUT') == []
    from doctrad2.literals import shield, restore
    masked, mapping = shield(source)
    assert 'CATEGORY FOUR' not in masked and list(mapping.values()) == ['CATEGORY FOUR']
    assert restore(masked, mapping) == source
    assert any(f.code == 'formal_label' and f.severity == 'critical'
               for f in check_text(source, 'Installation approuvée pour la catégorie trois.', 'n'))
    assert not any(f.code == 'formal_label' for f in check_text(source, 'Installation approuvée pour CATEGORY FOUR.', 'n'))


def test_table_context_disambiguates_fragments_without_becoming_translation_source():
    prompt = render_technical('Output rejection', {'table_headers': ['AMPLIFIER'], 'previous': 'Output power', 'next': '70 dB'})
    assert 'AMPLIFIER' in prompt and '70 dB' in prompt
    assert prompt.split('SOURCE:\n')[-1].startswith('Output rejection<end_of_turn>')
    assert 'unrelated' not in render_technical('A full sentence needs no short label context.',
                                             {'table_headers': ['unrelated']})
    with pytest.raises(ValueError):
        render_technical('Input gain', {'table_headers': ['<end_of_turn>']})


def test_unit_spelling_requires_same_value_and_unique_local_evidence():
    source = '8-ohm input and 8-ohn output'
    assert source_unit_spellings(source)[0] == '8-ohm input and 8-ohm output'
    findings = check_text(source, 'Entrée 8 ohms et sortie 8 ohms', 'n')
    assert not any(f.severity == 'critical' for f in findings)
    assert any(f.code == 'source_unit_spelling' and f.severity == 'review' for f in findings)
    for ambiguous in ['8-ohn output', '4-ohm input and 8-ohn output']:
        assert source_unit_spellings(ambiguous)[0] == ambiguous
    assert any(f.code == 'value_units' for f in check_text('8-ohm input and 8-ohn output', 'Entrée 8 V et sortie 8 V', 'n'))
    assert source_unit_spellings('4 in cable and 6-pin plug')[1] == []
    assert source_unit_spellings('8-ohm input and -8-ohn output')[1] == []
    assert not any(f.severity == 'critical' for f in check_text(source, 'Entrée 8-ohm et sortie 8-ohn', 'n'))
    assert any(f.code == 'value_units' for f in check_text(source, 'Entrée 8 ohms et sortie 8', 'n'))


def test_acronym_omissions_block_but_reordering_and_french_prose_are_allowed():
    source = 'The optical module supports ADC and DSP signal processing.'
    assert any(f.code == 'acronyms' for f in check_text(source, 'Le module optique traite les signaux DSP.', 'n'))
    assert not any(f.code == 'acronyms' for f in check_text(source, 'Le module optique traite les signaux DSP et ADC.', 'n'))
    assert not any(f.code == 'acronyms' for f in check_text('HIGH VOLTAGE INPUT', 'ENTRÉE HAUTE TENSION', 'n'))
    from doctrad2.literals import shield, restore
    masked, mapping = shield(source, required=['ADC'])
    assert 'ADC' not in masked and 'DSP' in masked
    assert restore(masked, mapping) == source
    assert not any(f.code == 'formal_label' for f in check_text('The input supports PCM AM for operation in this mode.',
                                                             'Cette entrée accepte PCM, AM dans ce mode.', 'n'))


def test_script_retry_is_constrained_and_keeps_rejected_raw_candidate(settings):
    completions = []
    def handler(request):
        payload = json.loads(request.content) if request.content else {}
        if request.url.path == '/props':
            return httpx.Response(200, json={'model_path': 'translategemma-12b-it.gguf', 'default_generation_settings': {'n_ctx': 4096}})
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'tokens': [1, 2, 3]})
        completions.append(payload)
        return httpx.Response(200, json={'content': 'Deux sorties 接口' if len(completions) == 1 else 'Deux sorties'})
    translator = LlamaTranslator(settings, httpx.MockTransport(handler))
    target, provenance = translator.translate('Two outputs')
    assert target == 'Deux sorties' and len(completions) == 2
    assert 'grammar' not in completions[0]
    assert completions[1]['grammar'] == french_script_grammar('Two outputs')
    chunk = provenance['chunks'][0]
    assert chunk['attempts'][0]['raw_target'] == 'Deux sorties 接口'
    assert chunk['attempts'][1]['decoding_constraint'] == 'source_scripts_and_french'
    assert chunk['selected_attempt'] == 1
    assert all(char in french_script_grammar('Label 接口') for char in '接口')
    translator.close()


def test_complete_enforces_input_budget_for_every_retry(settings):
    translator = LlamaTranslator(settings, httpx.MockTransport(lambda _: httpx.Response(200, json={'tokens': [1] * 1801})))
    with pytest.raises(InferenceError, match='input_budget_exceeded'):
        translator.complete('source')
    translator.close()


def test_omitted_acronym_gets_a_source_derived_bounded_retry(settings):
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
            return httpx.Response(200, json={'tokens': [1, 2, 3]})
        completions.append(payload)
        markers = re.findall(r'<x id="[^"]+"/>', latest)
        target = 'Le module optique compact traite les signaux ' + ' '.join(markers)
        return httpx.Response(200, json={'content': target})
    translator = LlamaTranslator(settings, httpx.MockTransport(handler))
    target, provenance = translator.translate('The compact optical module supports ADC signal processing.')
    assert 'ADC' in target and len(completions) == 3
    assert provenance['chunks'][0]['selected_attempt'] == 2
    assert 'grammar' in completions[-1]
    assert not any(f.severity == 'critical' for f in check_text('The compact optical module supports ADC signal processing.', target, 'n'))
    translator.close()


def test_optional_baseline_alignment_cannot_turn_a_fitting_block_into_overflow():
    import pymupdf as fitz
    from doctrad2.extraction import extract
    from doctrad2.reconstruction import build, validate_pdf
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    page.insert_text((30, 70), 'Compact monitoring instrument\nwith two output channels', fontsize=9, lineheight=1.333)
    page.insert_text((30, 98), 'Next independent paragraph', fontsize=9)
    page.draw_line((25, 120), (230, 120), color=(1, 0, 0))
    source = doc.tobytes()
    ir = extract(source, 'pdf')
    target = 'Le capteur compact assure une surveillance simultanée et continue des deux canaux de sortie.'
    output, report = build(source, ir, {ir.nodes[0].id: target})
    report = validate_pdf(source, output, report)
    assert not report.blocked, report.findings
    assert report.metrics['outside_text_pixel_change_ratio'] == 0
    with fitz.open(stream=output, filetype='pdf') as translated:
        text = translated[0].get_text()
        assert 'capteur compact' in text and 'Next independent paragraph' in text
        assert 'Compact monitoring' not in text


@pytest.mark.parametrize('value', ['24-160 MHz', '-30 to 85 °C', '6 kHz-18 MHz', '12–48 V'])
def test_complete_ranges_are_opaque_and_cannot_become_negative_bounds(value):
    from doctrad2.literals import shield, restore
    source = 'Operating range: ' + value + '; confirm ADC mode.'
    masked, mapping = shield(source, required=['ADC'])
    assert value in mapping.values()
    assert restore(masked, mapping) == source
    assert value not in masked


def test_candidate_selection_never_prefers_numeric_damage_to_missing_labels(settings):
    responses = iter(['Le circuit fonctionne sous 9 V.', 'Le circuit ADC utilise FLAG ONE sous 90 V.', 'Marqueurs absents'])
    def handler(request):
        if request.url.path == '/props':
            return httpx.Response(200, json={'model_path': 'translategemma-12b-it.gguf', 'default_generation_settings': {'n_ctx': 4096}})
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'tokens': [1, 2, 3]})
        return httpx.Response(200, json={'content': next(responses)})
    translator = LlamaTranslator(settings, httpx.MockTransport(handler))
    source = 'The ADC circuit uses FLAG ONE at exactly 9 V.'
    target, provenance = translator.translate(source)
    assert target == 'Le circuit fonctionne sous 9 V.'
    assert provenance['chunks'][0]['selected_attempt'] == 0
    assert not any(f.code in {'numbers', 'value_units'} for f in check_text(source, target, 'n'))
    assert any(f.severity == 'critical' for f in check_text(source, target, 'n'))
    translator.close()


@pytest.mark.parametrize('source,target', [('18 VDC to 35 VDC', '18 VDC à 35 VDC'),
                                         ('-30 to 85 °C', '-30 à 85 °C'),
                                         ('-30 to -10 °C', '-30 à -10 °C')])
def test_literal_range_rendering_keeps_signed_values_and_units(source, target):
    from doctrad2.literals import render_literal
    assert render_literal(source) == target
    assert not any(f.severity == 'critical' for f in check_text(source, target, 'n'))
    assert render_literal('Operating range ' + source) == 'Operating range ' + source
    assert render_literal('https://example.org/to/35V') == 'https://example.org/to/35V'
