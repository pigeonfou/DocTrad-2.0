#!/usr/bin/env python3
"""Public, independent prompt experiment; no production translation is rewritten here."""
import json
import re
from pathlib import Path
from doctrad2.config import Settings
from doctrad2.db import Database
from doctrad2.gpu_lock import gpu_lock
from doctrad2.inference import LlamaTranslator
from doctrad2.quality import check_text
from doctrad2.technical_prompt import render_technical

RULES = ('Translate faithfully and concisely for technical documentation. Preserve the exact meaning, '
         'degree and hierarchy of all qualifiers, numbers, units, negations and formal labels. '
         'Do not convert units, expand acronyms, paraphrase identifiers or add explanations. ')
CASES = [
    ('classification', 'The maximum security level is TOP SECRET.'),
    ('safety', 'Do not disconnect the protective earth conductor.'),
    ('compound', 'A compact dual-channel recorder supports synchronous capture.'),
    ('dimensions', 'Dimensions: 2 H x 4 W x 6 D in (with battery).'),
    ('label', 'UHF SATCOM Waveforms'),
    ('degree', 'The pressure must never exceed 7 bar.'),
    ('portable_channels', 'Multiple capabilities in a single, compact dual-channel manpack speeds deployment and reduces costs for dismount and vehicular missions'),
    ('short_network', 'High-speed tactical MANETs expand real-time networking'),
    ('technical_term', 'Spurious Suppression'),
    ('formal_degree', 'High Assurances architecture allows Multiple Independent Levels of Security (MILS) up to TOP SECRET'),
    ('unrelated_channels', 'The compact dual-channel oscilloscope supports simultaneous acquisition on both inputs.'),
    ('acronyms', 'The external module supports ISR video and SATCOM, with in-field updates as mission needs evolve.'),
    ('other_formal_label', 'All devices shall meet the required safety class CATEGORY FOUR.'),
]

FRENCH_RULES = ('Traduisez en français technique précis et concis. Conservez chaque information, '
                'les sigles, valeurs, unités, négations et le degré exact des qualificatifs. '
                'Ne développez pas les sigles. Ne convertissez pas les unités. '
                'Répondez uniquement avec la traduction, intégralement en français.\nTexte anglais :\n')
LATIN_GRAMMAR = r'root ::= [\t\n\r\x20-\x7E\u00A0-\u024F\u0300-\u03FF\u1E00-\u1EFF\u2000-\u23FF\u25A0-\u27BF]*'


def generate(translator, prompt, grammar=None):
    tokens = translator.request('/tokenize', {'content': prompt, 'add_special': False, 'parse_special': True})['tokens']
    if len(tokens) > translator.contract.input_tokens:
        raise ValueError('experiment_input_budget_exceeded')
    payload = {'prompt': tokens, 'n_predict': translator.contract.output_tokens,
               'temperature': 0, 'seed': 42, 'cache_prompt': True, 'stream': False}
    if grammar:
        payload['grammar'] = grammar
    result = translator.request('/completion', payload)
    if result.get('stopped_limit') or result.get('truncated') or result.get('stop_type') == 'limit':
        raise ValueError('experiment_output_truncated')
    return result['content'].strip(), {'input_tokens': len(tokens), 'timings': result.get('timings')}


def main():
    settings = Settings.load()
    results = []
    with gpu_lock(Database(settings.database_url), settings.root) as admitted:
        if not admitted:
            print('Public prompt experiment skipped: worker busy')
            return
        translator = LlamaTranslator(settings)
        try:
            translator.validate()
            for label, source in CASES:
                if label not in {'formal_degree', 'classification', 'technical_term', 'other_formal_label'}:
                    continue
                labels = re.findall(r'\b[A-Z]{2,}(?:[ -]+[A-Z]{2,})+\b', source)
                extra = 'Retain these source labels verbatim, without translation or substitution: ' + json.dumps(labels) + '.\n' if labels else ''
                if label == 'technical_term':
                    extra += 'Context (not to translate): table heading TRANSMITTER; neighboring value > -53dBc.\n'
                guarded = render_technical(source).replace('\nSOURCE:\n', '\n' + extra + 'SOURCE:\n')
                mapping = {}
                def mark(match):
                    marker = 'dtprobe-' + str(len(mapping))
                    mapping[marker] = match.group()
                    return '<x id="' + marker + '"/>'
                masked = re.sub(r'\b[A-Z]{2,}(?:[ -]+[A-Z]{2,})+\b', mark, source)
                masked_prompt = render_technical(masked)
                if label == 'technical_term':
                    masked_prompt = masked_prompt.replace('\nSOURCE:\n', '\nContext (not to translate): table heading TRANSMITTER; neighboring value > -53dBc.\nSOURCE:\n')
                prompts = {
                    'masked_labels': (masked_prompt, LATIN_GRAMMAR),
                    'context_labels': (guarded, LATIN_GRAMMAR),
                }
                for profile, (prompt, grammar) in prompts.items():
                    target, info = generate(translator, prompt, grammar)
                    if profile == 'masked_labels':
                        from doctrad2.literals import restore
                        info['raw_target'] = target
                        target = restore(target, mapping) or 'INVALID_MARKERS: ' + target
                    results.append({'case': label, 'profile': profile, 'source': source, 'target': target,
                                    'findings': [f.model_dump() for f in check_text(source, target, label)], 'generation': info})
        finally:
            translator.close()
    destination = Path('/var/lib/doctrad2-reference/prompt-experiment.json')
    destination.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    destination.chmod(0o644)
    print('PUBLIC_PROMPT_EXPERIMENT=' + json.dumps([{'case': r['case'], 'profile': r['profile'], 'target': r['target']} for r in results], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

