"""Source-derived constraints: no document vocabulary or identifier allowlist."""
import re

CONSTRAINT_VERSION = 'source-derived-1'
LATIN_CHARACTERS = r'\t\n\r\x20-\x7E\u00A0-\u024F\u0300-\u03FF\u1E00-\u1EFF\u2000-\u23FF\u25A0-\u27BF'


def source_labels(text):
    # All-uppercase headings are ordinary translation units. Inside prose,
    # multiword uppercase expressions are retained as source labels.
    if len(text.split()) < 7 or not re.search(r'[a-z]', text):
        return []
    return list(dict.fromkeys(re.findall(r'\b[A-Z]{2,}(?:[ -]+[A-Z]{2,})+\b', text)))


def french_script_grammar(source):
    # French, technical symbols and any alphabetic characters already present
    # in the source remain possible. Never remove characters after generation.
    extra = ''.join(sorted({c for c in source if ord(c) > 0x27BF or 0x0400 <= ord(c) < 0x1E00}))
    return 'root ::= [' + LATIN_CHARACTERS + extra + ']*'
