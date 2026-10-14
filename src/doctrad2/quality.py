from collections import Counter
from decimal import Decimal, InvalidOperation
import re
from .domain import Finding

NUMBER = re.compile(r"(?<![\w])[-+−]?\d+(?:[.,]\d+)?(?:\s*[eE][-+]?\d+)?")
IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9_./-]*[A-Za-z])(?=[A-Za-z0-9_./-]*\d)[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+\b")
UNITS = {"V": "V", "mV": "mV", "kV": "kV", "A": "A", "mA": "mA", "Hz": "Hz", "kHz": "kHz", "MHz": "MHz", "GHz": "GHz", "W": "W", "kW": "kW", "Ω": "Ω", "ohm": "Ω", "ohms": "Ω", "mm": "mm", "cm": "cm", "km": "km", "ms": "ms", "µs": "µs", "ns": "ns", "dB": "dB", "dBm": "dBm", "°C": "°C", "%": "%", "mile": "mile", "miles": "mile", "MHz/s": "MHz/s"}


def numbers(text):
    values = []
    for match in NUMBER.finditer(text):
        try:
            values.append(str(Decimal(match.group().replace("−", "-").replace(",", ".").replace(" ", "")).normalize()))
        except InvalidOperation:
            values.append(match.group())
    return Counter(values)


def measured_values(text):
    result = []
    # Pair value and unit to detect swaps that a global numeric multiset would miss.
    pattern = re.compile(r"([-+−]?\d+(?:[.,]\d+)?)\s*(" + "|".join(re.escape(x) for x in sorted(UNITS, key=len, reverse=True)) + r")(?![A-Za-z])")
    for m in pattern.finditer(text):
        result.append((str(Decimal(m[1].replace("−", "-").replace(",", ".")).normalize()), UNITS[m[2]]))
    return Counter(result)


def check_text(source, target, unit_id, glossary=None):
    findings = []
    def add(code, severity, detail):
        findings.append(Finding(code=code, severity=severity, unit_id=unit_id, detail=detail))
    if not target or not target.strip():
        add("empty_target", "critical", "Traduction absente")
        return findings
    if numbers(source) != numbers(target):
        add("numbers", "critical", "Valeurs numériques ajoutées, omises ou modifiées")
    if measured_values(source) != measured_values(target):
        add("value_units", "critical", "Association valeur/unité modifiée")
    if Counter(IDENTIFIER.findall(source)) != Counter(IDENTIFIER.findall(target)):
        add("identifiers", "critical", "Référence technique ajoutée, omise ou modifiée")
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
