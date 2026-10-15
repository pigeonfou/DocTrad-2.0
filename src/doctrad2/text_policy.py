"""Document-independent preprocessing. No document identifiers, vocabulary or replacements."""
import re

POLICY_VERSION = 'technical-flow-2.2'


def translation_source(text):
    # PDF soft wraps are layout, not sentence boundaries. A hyphen at a line break
    # remains a hyphen (a product name must not be silently rewritten).
    text = re.sub(r'(?<=-)[ \t]*\n[ \t]*(?=\w)', '', text)
    return re.sub(r'[ \t]*\n[ \t]*', ' ', text).strip()


def sentence_parts(text):
    """A bounded alternative for candidates failing fidelity checks; retain all source text."""
    return [p for p in re.split(r'(?<=[.!?;])\s+(?=[A-Z0-9])', text) if p]
