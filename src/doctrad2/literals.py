"""Source-derived opaque spans for a final, bounded fidelity retry."""
import hashlib
import re
from .quality import UNIT_PATTERN, IDENTIFIER, identifiers

URL = re.compile(r'(?:https?://|www\.)[^\s<>]+')
QUANTITY = re.compile(r'[-+−–]?\d+(?:[.,]\d+)?\s*[- ]?\s*(?:' + UNIT_PATTERN + r')(?:\^?[23]|[²³])?(?![A-Za-z])')
DIMENSIONS = re.compile(r'(?:\d+(?:[.,]\d+)?\s*(?:[HWD]\s*)?[x×]\s*){1,2}\d+(?:[.,]\d+)?\s*(?:[HWD]\s*)?(?:' + UNIT_PATTERN + r')(?![A-Za-z])')


def protected_spans(text):
    chosen = []
    def add(match):
        if any(match.start() < end and match.end() > start for start, end in chosen):
            return
        chosen.append((match.start(), match.end()))
    for pattern in (URL, DIMENSIONS):
        for match in pattern.finditer(text):
            add(match)
    refs = identifiers(text)
    for match in IDENTIFIER.finditer(text):
        if any(value in refs for value in identifiers(match.group())):
            add(match)
    for match in QUANTITY.finditer(text):
        if re.search(r'\bin$', match.group()) and re.match(r'\s+(?![xX]\b)[A-Za-z]', text[match.end():]):
            continue
        add(match)
    return sorted(chosen)


def shield(text):
    spans = protected_spans(text)
    prefix = 'dt' + hashlib.sha256(text.encode()).hexdigest()[:8]
    chunks, mapping, cursor = [], {}, 0
    for index, (start, end) in enumerate(spans):
        name = prefix + '-' + str(index)
        mapping[name] = text[start:end]
        chunks.extend([text[cursor:start], f'<x id="{name}"/>'])
        cursor = end
    chunks.append(text[cursor:])
    return ''.join(chunks), mapping


def restore(text, mapping):
    pattern = re.compile(r'<x\s+id=[\'\"]([^\'\"]+)[\'\"]\s*/>', re.I)
    names = pattern.findall(text)
    if sorted(names) != sorted(mapping):
        return None
    return pattern.sub(lambda m: mapping[m[1]], text)


def literal_only(text):
    spans = protected_spans(text)
    rest, cursor = [], 0
    for start, end in spans:
        rest.append(text[cursor:start])
        cursor = end
    rest.append(text[cursor:])
    return bool(spans) and not any(c.isalnum() for c in ''.join(rest))
