"""Geometry and source-style decisions independent of a document's content."""
from collections import Counter
import html
import re
import pymupdf as fitz
from .text_policy import translation_source

COMPOSITION_VERSION = "bounded-style-2.5"


def source_style(node):
    runs = [r for r in node.runs if r.text.strip()]
    if not runs:
        return 10, 0, 0
    weights = [max(1, len(re.sub(r'\W', '', r.text))) for r in runs]
    styles = Counter()
    for run, weight in zip(runs, weights):
        styles[(run.color, run.flags)] += weight
    color, flags = styles.most_common(1)[0][0]
    ordered = sorted(zip(runs, weights), key=lambda item: item[0].size)
    threshold, total = sum(weights) / 2, 0
    for run, weight in ordered:
        total += weight
        if total >= threshold:
            return max(1, run.size), color, flags


def text_markup(node, target):
    size, color, flags = source_style(node)
    source = translation_source(node.text)
    if node.kind == 'table_cell' and len(source.split()) < 8 and not source.endswith(('.', '!', '?', ';', ':')):
        target = target.rstrip().removesuffix('.')
    letters = ''.join(c for c in source if c.isalpha())
    if len(letters) > 3 and letters.isupper():
        target = target.upper()
    bullet = re.match(r'^([>•›])\s+(?=[A-Za-z])', source)
    prefix = ''
    if bullet and node.runs:
        symbol = bullet[1]
        if target.startswith(symbol):
            target = target[len(symbol):].lstrip()
        prefix = f'<span style="color:#{node.runs[0].color:06x}">{html.escape(symbol)} </span>'
    baselines = sorted({round(r.origin[1], 2) for r in node.runs if r.origin})
    gaps = [b-a for a, b in zip(baselines, baselines[1:]) if b-a > size * .6]
    leading = sorted(gaps)[len(gaps)//2] / size if gaps and size >= 13 else 1.1
    if node.kind == 'table_cell':
        leading = 1.05
    leading = min(1.5, max(1.05, leading))
    style = (f'body,div {{margin:0;padding:0;line-height:{leading};font-family:sans-serif;'
             f'font-size:{size}pt;color:#{color:06x};font-weight:{"bold" if flags & 16 else "normal"};'
             f'font-style:{"italic" if flags & 2 else "normal"};}}')
    return '<div>' + prefix + html.escape(target).replace('\n', '<br>') + '</div>', style


def placement_box(node, page, nodes):
    original = fitz.Rect(node.bbox)
    if node.kind == 'table_cell' and 'cell_bbox' in node.locator:
        cell = fitz.Rect(node.locator['cell_bbox'])
        return cell + (.5, .5, -.5, -.5)
    if node.locator.get('text_rotation', 0) or abs(node.locator.get('text_angle', 0)) > 1:
        return original
    size, _, _ = source_style(node)
    # Leave a physical gutter between text columns, and never cross an image/background edge.
    right = min(page.rect.x1 - 12, original.x1 + max(size * 4, original.width * .35))
    text_obstacles = [fitz.Rect(n.bbox) for n in nodes if n.id != node.id and n.bbox]
    graphics = [fitz.Rect(b['bbox']) for b in page.get_text('dict')['blocks'] if b['type'] == 1]
    graphics += [fitz.Rect(d['rect']) for d in page.get_drawings()]
    for obstacle in text_obstacles:
        if obstacle.y0 < original.y1 and obstacle.y1 > original.y0 and obstacle.x0 >= original.x1:
            right = min(right, obstacle.x0 - max(4, size * .5))
    for obstacle in graphics:
        if obstacle.y0 < original.y1 and obstacle.y1 > original.y0 and obstacle.x0 >= original.x1:
            right = min(right, obstacle.x0 - 1)
    right = max(original.x1, right)
    bottom = min(page.rect.y1 - 12, original.y1 + max(size * 2, original.height * .35))
    for obstacle in text_obstacles + graphics:
        if obstacle.x0 < right and obstacle.x1 > original.x0 and obstacle.y0 >= original.y1 - .1:
            bottom = min(bottom, obstacle.y0 - 1)
    return fitz.Rect(original.x0, original.y0, right, max(original.y1, bottom))
