"""Conservative source-backed corrections, never numeric conversion or a vocabulary list."""
from collections import defaultdict
from decimal import Decimal
import re
from .quality import measured_values, numbers, UNIT_PATTERN, UNITS


def restore_unambiguous_units(source, target):
    """Restore only a unit attached to an unchanged, unambiguous measured value.

    If values changed (including an attempted conversion), or one value has several
    source units, do not guess. Keep the candidate and let quality block it.
    """
    if numbers(source) != numbers(target):
        return target, []
    units = defaultdict(set)
    for (value, unit), count in measured_values(source).items():
        units[value].add(unit)
    repairs = []
    pattern = re.compile(r'([-+−–]?\d+(?:[.,]\d+)?)\s*(' + UNIT_PATTERN + r')(?![A-Za-z])')
    def replace(match):
        if match[2] == 'in' and re.match(r'\s+[a-zA-Z]', target[match.end():]):
            return match.group()
        value = str(Decimal(match[1].replace('−', '-').replace('–', '-').replace(',', '.')).normalize())
        expected = units.get(value, set())
        if len(expected) != 1 or UNITS[match[2]] in expected:
            return match.group()
        unit = next(iter(expected))
        repairs.append({'value': value, 'candidate_unit': match[2], 'source_unit': unit})
        return match[1] + ' ' + unit
    corrected = pattern.sub(replace, target)
    # Reject repairs that still do not reproduce the source quantity multiset.
    if repairs and measured_values(corrected) != measured_values(source):
        return target, []
    return corrected, repairs
