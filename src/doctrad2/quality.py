from collections import Counter
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from .domain import Finding
from .constraints import source_labels

NUMBER = re.compile(r"[-+−–]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")
IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9_./-]*[A-Za-z])(?=[A-Za-z0-9_./-]*\d)[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+\b")
UNITS = {x: x for x in ("V mV kV A mA Hz kHz MHz GHz W kW mm cm km ms µs ns dB dBm °C % MHz/s kg g m").split()}
UNITS.update({"Ω": "Ω", "ohm": "Ω", "ohms": "Ω", "mile": "mile", "miles": "mile",
              "meter": "m", "meters": "m", "mètre": "m", "mètres": "m", "in": "in",
              "inch": "in", "inches": "in", "pouce": "in", "pouces": "in", "ft": "ft",
              "feet": "ft", "foot": "ft", "pied": "ft", "pieds": "ft", "lbs": "lb", "lb": "lb",
              "pound": "lb", "pounds": "lb", "livre": "lb", "livres": "lb"})
QUALITY_VERSION = 'physical-quantities-2.7'
UNITS.update({'watt': 'W', 'watts': 'W', 'volt': 'V', 'volts': 'V', 'ampere': 'A', 'amperes': 'A',
              'ampère': 'A', 'ampères': 'A', 'bar': 'bar', 'bars': 'bar', 'Pa': 'Pa', 'kPa': 'kPa',
              'MPa': 'MPa', 'mbar': 'mbar', 'psi': 'psi', '°F': '°F', 'K': 'K', 'dBc': 'dBc',
              'VDC': 'VDC', 'VCC': 'VDC', 'Vcc': 'VDC', 'VAC': 'VAC', 'N': 'N', 'Nm': 'Nm',
              'J': 'J', 'kJ': 'kJ', 'Wh': 'Wh', 'kWh': 'kWh', 'L': 'L', 'ml': 'ml', 'rpm': 'rpm'})
UNIT_PATTERN = "|".join(re.escape(x) for x in sorted(UNITS, key=len, reverse=True))


def identifiers(text, source_hints=None):
    result = []
    for match in IDENTIFIER.finditer(text):
        value = match.group()
        # A numeric descriptor (6-pin, 3-axis) is translated, not an immutable reference.
        if re.fullmatch(r"\d+-[a-z]+", value):
            continue
        if value.split('-')[0] in UNITS:
            continue
        if re.fullmatch(r"[A-Z]+-\d+", value) and re.match(r"\s*(?:" + UNIT_PATTERN + r")(?!\w)", text[match.end():]):
            continue
        result.append(value)
    hints = re.findall(r"\b([A-Z][a-z]{2,})-(\d+)\b", source_hints if source_hints is not None else text)
    for prefix, value in hints:
        canonical = prefix.casefold() + '-' + value
        result = [x for x in result if x.casefold() != canonical]
        matches = re.findall(r"(?i)\b" + re.escape(prefix) + r"[- ]?" + re.escape(value) + r"\b", text)
        result.extend([canonical] * len(matches))
    return Counter(result)


def numeric_text(text):
    # Distinguish range separators from signs using recognized physical units.
    return re.sub(r"(?<![A-Za-z])(" + UNIT_PATTERN + r")\s*-\s*(?=\d)", r"\1 to ", text)


def numbers(text):
    values = []
    text = numeric_text(text)
    # Unit exponents are dimensions, not added scalar values (m3 / m³ / cubic metres).
    text = re.sub(r"(?<![A-Za-z])(" + UNIT_PATTERN + r")(?:\^?[23]|[²³])(?![A-Za-z0-9])", r"\1", text)
    # Include numbers embedded in versions and references; matching all components
    # avoids the old 'v2' vs 'version 2' discrepancy.
    for match in NUMBER.finditer(text):
        value = match.group().replace('−', '-').replace('–', '-').replace(',', '.')
        # A hyphen inside an alphanumeric reference is a separator, not a sign.
        if value.startswith('-') and match.start() and text[match.start()-1].isalnum():
            prefix = text[:match.start()]
            if not re.search(r"(?:^|\s)[A-Z]{1,3}$", prefix):
                value = value[1:]
        try:
            values.append(str(Decimal(value).normalize()))
        except InvalidOperation:
            values.append(value)
    return Counter(values)


def measured_values(text):
    result = []
    text = numeric_text(text)
    # Dimension triplets share their trailing unit, even when axis labels occur.
    dimension = re.compile(r"((?:\d+(?:[.,]\d+)?\s*(?:[A-Za-z]\s*)?[x×]\s*){1,2}\d+(?:[.,]\d+)?\s*(?:[A-Za-z]\s*)?)\s*(?:\(?\s*(?:en|in)\s+)?(" + UNIT_PATTERN + r")(?![A-Za-z])")
    def expand(match):
        return ' '.join(v + ' ' + ('inch' if match[2] == 'in' else match[2]) for v in re.findall(r"\d+(?:[.,]\d+)?", match[1]))
    text = dimension.sub(expand, text)
    pattern = re.compile(r"(?P<value>[-+−–]?\d+(?:[.,]\d+)?)\s*[- ]?\s*(?:(?P<prefix>cubic|square)\s+)?(?P<unit>" + UNIT_PATTERN + r")(?:(?:\^?(?P<power>[23]))|(?P<super>[²³])|\s+(?P<word>cubes?|cubed|carrés?|squared))?(?![A-Za-z])")
    for m in pattern.finditer(text):
        power = m['power'] or ({'²': '2', '³': '3'}.get(m['super']))
        if m['prefix'] or m['word']:
            power = '3' if (m['prefix'] or m['word']).startswith('cub') else '2'
        if not power and m['unit'] == 'in' and re.match(r'\s+(?![xX]\b)[A-Za-z]', text[m.end():]):
            continue
        if m['unit'] in {'W', 'A', 'V'} and re.match(r"\.\s+[A-Z][A-Za-z]+", text[m.end():]) and re.search(r'\b\d{4,6}[.,]?\s*$', text) and len(re.findall(r'\b\d{3,6}\b', text)) >= 2:
            continue
        unit = UNITS[m['unit']] + ('^' + power if power else '')
        result.append((str(Decimal(m['value'].replace('−', '-').replace('–', '-').replace(',', '.')).normalize()), unit))
    return Counter(result)


def scripts(text):
    result = set()
    for char in text:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, '')
        if name.startswith(('CJK ', 'HIRAGANA ', 'KATAKANA ')):
            result.add('EAST_ASIAN')
        elif name.startswith(('CYRILLIC ', 'ARABIC ', 'HEBREW ', 'HANGUL ', 'DEVANAGARI ')):
            result.add(name.split()[0])
    return result


def source_unit_spellings(text):
    """Identify a single-letter unit inconsistency backed by the same source value.

    This never changes the uploaded source. A matching translation still requires
    human review; absent or competing source evidence leaves the critical check intact.
    """
    pattern = re.compile(r'(?P<value>\d+(?:[.,]\d+)?)\s*[- ]\s*(?P<word>[a-z]{3,})(?![A-Za-z])')
    matches = list(pattern.finditer(text))
    known = {}
    for match in matches:
        if match['word'] in UNITS:
            value = Decimal(match['value'].replace(',', '.'))
            known.setdefault(value, set()).add(match['word'])
    notes = []
    def replace(match):
        word = match['word']
        if word in UNITS:
            return match.group()
        alternatives = [unit for unit in known.get(Decimal(match['value'].replace(',', '.')), ())
                        if len(unit) == len(word) and sum(a != b for a, b in zip(unit, word)) == 1]
        if len(alternatives) != 1:
            return match.group()
        replacement = alternatives[0]
        notes.append({'source': word, 'supported_unit': replacement, 'value': match['value']})
        return match.group()[:match.start('word') - match.start()] + replacement
    return pattern.sub(replace, text), notes


def acronyms(text):
    return Counter(term for term in re.findall(r'\b([A-Z][A-Z0-9]{1,})(?:s)?\b', text)
                   if term not in UNITS)


def check_text(source, target, unit_id, glossary=None):
    findings = []
    def add(code, severity, detail):
        findings.append(Finding(code=code, severity=severity, unit_id=unit_id, detail=detail))
    if not target or not target.strip():
        add("empty_target", "critical", "Traduction absente")
        return findings
    if scripts(target) - scripts(source):
        add("unexpected_script", "critical", "Écriture étrangère ajoutée à une traduction française")
    if numbers(source) != numbers(target):
        add("numbers", "critical", "Valeurs numériques ajoutées, omises ou modifiées")
    qualified_source, unit_notes = source_unit_spellings(source)
    if measured_values(qualified_source) != measured_values(target):
        add("value_units", "critical", "Association valeur/unité modifiée")
    for note in unit_notes:
        add('source_unit_spelling', 'review',
            f"Unité source ambiguë « {note['source']} » pour {note['value']} ; « {note['supported_unit']} » apparaît avec la même valeur dans ce passage. Vérification requise.")
    if identifiers(source) != identifiers(target, source):
        add("identifiers", "critical", "Référence technique ajoutée, omise ou modifiée")
    if len(source.split()) >= 7 and re.search(r'[a-z]', source):
        if acronyms(source) - acronyms(target):
            add('acronyms', 'critical', 'Sigle source omis ou remplacé dans la traduction')
    # Generic review of emphasized phrases inside prose, without a vocabulary list.
    emphasized = re.findall(r"\b[A-Z]{2,}(?:[ -]+[A-Z]{2,})+\b", source)
    if re.search(r"[a-z]", source) and any(term not in target for term in emphasized):
        add("emphasized_phrase", "review", "Expression source en capitales traduite : vérifier le sens et le degré")
    if any(not re.search(r'\b' + r'[\W_]+'.join(re.escape(w) for w in re.findall(r'[A-Z0-9]+', label)) + r'\b', target)
           for label in source_labels(source)):
        add('formal_label', 'critical', 'Libellé source en capitales remplacé dans un passage : sens et degré non garantis')
    if len(target) > max(200, len(source) * 3) or len(target) < len(source) * .35:
        add("length_ratio", "review", "Rapport de longueur inhabituel : vérifier omission ou ajout")
    if target.strip().casefold() == source.strip().casefold() and len(source.split()) >= 5:
        add("unchanged", "review", "Passage long inchangé")
    if re.search(r"(?:https?://|www\.)", source) and re.findall(r"(?:https?://|www\.)\S+", source) != re.findall(r"(?:https?://|www\.)\S+", target):
        add("urls", "critical", "URL source modifiée")
    for term, translated in (glossary or {}).items():
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", source, re.I) and translated.casefold() not in target.casefold():
            add("glossary", "review", "Terme du glossaire absent de la traduction")
    return findings

