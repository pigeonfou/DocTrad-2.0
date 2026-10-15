from collections import Counter
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from .domain import Finding

NUMBER = re.compile(r"[-+−–]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")
IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9_./-]*[A-Za-z])(?=[A-Za-z0-9_./-]*\d)[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+\b")
UNITS = {x: x for x in ("V mV kV A mA Hz kHz MHz GHz W kW mm cm km ms µs ns dB dBm °C % MHz/s kg g m").split()}
UNITS.update({"Ω": "Ω", "ohm": "Ω", "ohms": "Ω", "mile": "mile", "miles": "mile",
              "meter": "m", "meters": "m", "mètre": "m", "mètres": "m", "in": "in",
              "inch": "in", "inches": "in", "pouce": "in", "pouces": "in", "ft": "ft",
              "feet": "ft", "foot": "ft", "pied": "ft", "pieds": "ft", "lbs": "lb", "lb": "lb",
              "pound": "lb", "pounds": "lb", "livre": "lb", "livres": "lb"})
UNIT_PATTERN = "|".join(re.escape(x) for x in sorted(UNITS, key=len, reverse=True))


def identifiers(text):
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
    return Counter(result)


def numeric_text(text):
    # Distinguish range separators from signs using recognized physical units.
    return re.sub(r"(?<![A-Za-z])(" + UNIT_PATTERN + r")\s*-\s*(?=\d)", r"\1 to ", text)


def numbers(text):
    values = []
    text = numeric_text(text)
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
    dimension = re.compile(r"((?:\d+(?:[.,]\d+)?\s*(?:[HWD]\s*)?[x×]\s*){1,2}\d+(?:[.,]\d+)?\s*(?:[HWD]\s*)?)\s*(" + UNIT_PATTERN + r")(?![A-Za-z])")
    def expand(match):
        return ' '.join(v + ' ' + match[2] for v in re.findall(r"\d+(?:[.,]\d+)?", match[1]))
    text = dimension.sub(expand, text)
    pattern = re.compile(r"([-+−–]?\d+(?:[.,]\d+)?)\s*[- ]?\s*(" + UNIT_PATTERN + r")(?![A-Za-z])")
    for m in pattern.finditer(text):
        if m[2] in {'W', 'A', 'V'} and re.match(r"\.\s+[A-Z][A-Za-z]+", text[m.end():]):
            continue  # Abbreviated proper-name/address component, not a measurement.
        result.append((str(Decimal(m[1].replace('−', '-').replace('–', '-').replace(',', '.')).normalize()), UNITS[m[2]]))
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
    if measured_values(source) != measured_values(target):
        add("value_units", "critical", "Association valeur/unité modifiée")
    if identifiers(source) != identifiers(target):
        add("identifiers", "critical", "Référence technique ajoutée, omise ou modifiée")
    # Generic review of emphasized phrases inside prose, without a vocabulary list.
    emphasized = re.findall(r"\b[A-Z]{2,}(?:[ -]+[A-Z]{2,})+\b", source)
    if re.search(r"[a-z]", source) and any(term not in target for term in emphasized):
        add("emphasized_phrase", "review", "Expression source en capitales traduite : vérifier le sens et le degré")
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
