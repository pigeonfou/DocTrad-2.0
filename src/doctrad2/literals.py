"""Source-derived opaque spans for a final, bounded fidelity retry."""
import hashlib
import re
from .quality import UNIT_PATTERN, IDENTIFIER, identifiers
from .constraints import source_labels

URL = re.compile(r'(?:https?://|www\.)[^\s<>]+')
QUANTITY = re.compile(r'[-+−–]?\d+(?:[.,]\d+)?\s*[- ]?\s*(?:' + UNIT_PATTERN + r')(?:\^?[23]|[²³])?(?![A-Za-z])')
DIMENSIONS = re.compile(r'(?:\d+(?:[.,]\d+)?\s*(?:[HWD]\s*)?[x×]\s*){1,2}\d+(?:[.,]\d+)?\s*(?:[HWD]\s*)?(?:' + UNIT_PATTERN + r')(?![A-Za-z])')
RANGE = re.compile(r'[-+−–]?\d+(?:[.,]\d+)?\s*(?:(?:' + UNIT_PATTERN + r')\s*)?'
                   r'(?:[-−–]|\bto\b|\bà\b)\s*[-+−–]?\d+(?:[.,]\d+)?\s*'
                   r'(?:' + UNIT_PATTERN + r')(?:\^?[23]|[²³])?(?![A-Za-z])')


def protected_spans(text, required=()):
    chosen = []
    def add(match):
        if any(match.start() < end and match.end() > start for start, end in chosen):
            return
        chosen.append((match.start(), match.end()))
    for pattern in (URL, DIMENSIONS, RANGE):
        for match in pattern.finditer(text):
            add(match)
    for label in source_labels(text):
        for match in re.finditer(re.escape(label), text):
            add(match)
    for word in required:
        for match in re.finditer(r'\b' + re.escape(word) + r'\b', text):
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


def shield(text, required=()):
    spans = protected_spans(text, required)
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


def render_literal(text):
    """Render only a numeric relation, leaving values, units and URLs intact."""
    if not literal_only(text):
        return text
    urls = [match.span() for match in URL.finditer(text)]
    def relation(match):
        if any(match.start() < end and match.end() > start for start, end in urls):
            return match.group()
        return re.sub(r'\s*\bto\b\s*', ' à ', match.group())
    return RANGE.sub(relation, text)

