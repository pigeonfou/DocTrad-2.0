#!/usr/bin/env python3
"""Public, independent prompt experiment; no production translation is rewritten here."""
import json
from pathlib import Path
from doctrad2.config import Settings
from doctrad2.db import Database
from doctrad2.gpu_lock import gpu_lock
from doctrad2.inference import LlamaTranslator
from doctrad2.quality import check_text

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
                context = ({'table_headers': ['TRANSMITTER'], 'previous': 'Output power', 'next': '> -53dBc'}
                           if label == 'technical_term' else None)
                target, info = translator.translate(source, context=context)
                results.append({'case': label, 'profile': 'qualified-production', 'source': source, 'target': target,
                                'findings': [f.model_dump() for f in check_text(source, target, label)], 'generation': info})
        finally:
            translator.close()
    destination = Path('/var/lib/doctrad2-reference/prompt-experiment.json')
    destination.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    destination.chmod(0o644)
    print('PUBLIC_PROMPT_EXPERIMENT=' + json.dumps([{'case': r['case'], 'profile': r['profile'], 'target': r['target']} for r in results], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

