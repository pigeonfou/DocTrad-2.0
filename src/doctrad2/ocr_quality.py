"""Read OCR formatting without repairing recognized content or certifying a page."""
from html.parser import HTMLParser
import re

from .quality import identifiers, measured_values, numbers


def math_format(text):
    # Only remove unambiguous inline TeX wrappers around square/cubic exponents.
    return re.sub(r"\\\(\s*\^\{([23])\}\s*\\\)", lambda m: "²" if m[1] == "2" else "³", text)


class OCRMarkup(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.issues = []

    def append(self, text):
        self.parts.append(text)
        if self.cell is not None:
            self.cell.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table is not None:
                self.issues.append("nested_table")
            else:
                self.table = []
        elif tag == "tr":
            if self.row is not None:
                self.issues.append("unclosed_row")
            self.row = []
        elif tag in {"td", "th"}:
            if any(name in {"colspan", "rowspan"} and value != "1" for name, value in attrs):
                self.issues.append("spanned_cell_requires_layout_review")
            if self.cell is not None:
                self.issues.append("unclosed_cell")
                self.finish_cell()
            self.cell = []
        elif tag in {"br", "p", "div"}:
            self.append("\n")
        elif tag == "sup":
            self.append("^")
        elif tag not in {"thead", "tbody", "tfoot", "span", "b", "strong", "i", "em"}:
            self.issues.append("unknown_markup_requires_review")
            self.append(self.get_starttag_text())

    def finish_cell(self):
        if self.cell is not None:
            if self.row is None:
                self.issues.append("cell_without_row")
                self.row = []
            self.row.append(math_format("".join(self.cell)).strip())
            self.cell = None
            self.parts.append("\t")

    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            self.finish_cell()
        elif tag == "tr":
            if self.cell is not None:
                self.issues.append("unclosed_cell")
                self.finish_cell()
            if self.row is not None:
                if self.table is None:
                    self.issues.append("row_without_table")
                else:
                    self.table.append(self.row)
                self.row = None
            self.parts.append("\n")
        elif tag == "table":
            if self.cell is not None or self.row is not None:
                self.issues.append("unclosed_table_content")
            if self.table is not None:
                self.tables.append(self.table)
                self.table = None
            self.parts.append("\n")
        elif tag in {"p", "div"}:
            self.append("\n")
        elif tag not in {"sup", "thead", "tbody", "tfoot", "span", "b", "strong", "i", "em", "br"}:
            self.append(f"</{tag}>")

    def handle_data(self, data):
        self.append(data)


def parse_ocr(text):
    text = re.sub(r"<\|det\|>.*?<\|/det\|>", "", text, flags=re.S)
    text = re.sub(r"(?m)^[ \t]*[A-Za-z_][\w-]*[ \t]*\[[0-9., \t+-]+\][ \t]*<\|/det\|>", "", text)
    text = re.sub(r"<\|/?(?:ref|grounding)\|>", "", text)
    for token in ("<｜end▁of▁sentence｜>", "<｜begin▁of▁sentence｜>", "<｜▁pad▁｜>"):
        text = text.replace(token, "")
    if not re.search(r"</?(?:table|tr|td|th|br|sup|p|div)\b", text, re.I):
        return {"text": math_format(text).strip(), "tables": [], "format_issues": []}
    parser = OCRMarkup()
    parser.feed(text)
    parser.close()
    if parser.table is not None or parser.row is not None or parser.cell is not None:
        parser.issues.append("incomplete_html")
    return {"text": math_format("".join(parser.parts)).strip(),
            "tables": parser.tables, "format_issues": sorted(set(parser.issues))}


def difference(expected, actual):
    def records(counter):
        return [{"value": value, "count": count} for value, count in sorted(counter.items())]
    return {"missing": records(expected - actual), "added": records(actual - expected)}


def compare_ocr(source, raw_target):
    parsed = parse_ocr(raw_target)
    target = parsed["text"]
    # Source is trusted reference text, not OCR markup. Preserve its angle brackets.
    source = math_format(source)
    counters = {
        "numbers": (numbers(source), numbers(target)),
        "physical_quantities": (measured_values(source), measured_values(target)),
        "identifiers": (identifiers(source), identifiers(target)),
    }
    checks = {name: difference(*pair) for name, pair in counters.items()}
    applicable = any(left or right for left, right in counters.values())
    mismatch = any(item["missing"] or item["added"] for item in checks.values())
    passed = bool(target.strip()) and not mismatch and not parsed["format_issues"]
    return {**parsed, "checks": checks, "technical_checks_applicable": applicable,
            "technical_checks_passed": passed if applicable else (None if target.strip() else False),
            "requires_review": True}
