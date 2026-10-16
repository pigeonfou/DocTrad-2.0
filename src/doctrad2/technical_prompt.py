"""Content-independent technical translation profile, qualified by public controls."""
import hashlib
import json
from .prompts import messages
from .constraints import CONSTRAINT_VERSION

RULES = ('Translate faithfully and concisely for technical documentation. Preserve the exact meaning, '
         'degree and hierarchy of all qualifiers, numbers, units, negations and formal labels. '
         'Do not convert units, expand acronyms, paraphrase identifiers or add explanations. ')
PREFIX = '<bos><start_of_turn>user\nTranslate the source from English to French. ' + RULES + '\nOutput only the French translation.\nSOURCE:\n'
SUFFIX = '<end_of_turn>\n<start_of_turn>model\n'
PROMPT_SHA = hashlib.sha256((PREFIX + '{source}' + SUFFIX + CONSTRAINT_VERSION).encode()).hexdigest()


def render_technical(text, context=None):
    messages(text)  # Same reserved-control-token validation as the pinned upstream template.
    extra = ''
    if context and len(text.split()) < 8 and context.get('table_headers'):
        hints = {'table_headings': context['table_headers'],
                 'previous': context.get('previous', '')[:160], 'next': context.get('next', '')[:160]}
        serialized = json.dumps(hints, ensure_ascii=False)
        messages(serialized)
        extra += 'Context (not to translate; only disambiguate the source): ' + serialized + '\n'
    return PREFIX.removesuffix('SOURCE:\n') + extra + 'SOURCE:\n' + text.strip() + SUFFIX

