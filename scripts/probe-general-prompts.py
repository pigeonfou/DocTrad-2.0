#!/usr/bin/env python3
"""Public, independent prompt experiment; no production translation is rewritten here."""
import json
from pathlib import Path
from doctrad2.config import Settings
from doctrad2.db import Database
from doctrad2.gpu_lock import gpu_lock
from doctrad2.inference import LlamaTranslator
from doctrad2.prompts import render

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
                official = render(source)
                prompts = {
                    'official': official,
                    'strict_official': official.replace('Produce only the French translation,', RULES + 'Produce only the French translation,', 1),
                    'strict_direct': '<bos><start_of_turn>user\nTranslate the source from English to French. ' + RULES + '\nOutput only the French translation.\nSOURCE:\n' + source + '<end_of_turn>\n<start_of_turn>model\n',
                }
                for profile, prompt in prompts.items():
                    target, info = translator.complete(prompt)
                    results.append({'case': label, 'profile': profile, 'source': source, 'target': target, 'generation': info})
        finally:
            translator.close()
    destination = Path('/var/lib/doctrad2-reference/prompt-experiment.json')
    destination.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    destination.chmod(0o644)
    print('PUBLIC_PROMPT_EXPERIMENT=' + json.dumps([{'case': r['case'], 'profile': r['profile'], 'target': r['target']} for r in results], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
