"""Content-independent technical translation profile, qualified by public controls."""
import hashlib
from .prompts import messages

RULES = ('Translate faithfully and concisely for technical documentation. Preserve the exact meaning, '
         'degree and hierarchy of all qualifiers, numbers, units, negations and formal labels. '
         'Do not convert units, expand acronyms, paraphrase identifiers or add explanations. ')
PREFIX = '<bos><start_of_turn>user\nTranslate the source from English to French. ' + RULES + '\nOutput only the French translation.\nSOURCE:\n'
SUFFIX = '<end_of_turn>\n<start_of_turn>model\n'
PROMPT_SHA = hashlib.sha256((PREFIX + '{source}' + SUFFIX).encode()).hexdigest()


def render_technical(text):
    messages(text)  # Same reserved-control-token validation as the pinned upstream template.
    return PREFIX + text.strip() + SUFFIX
