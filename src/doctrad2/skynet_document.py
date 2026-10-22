"""CPU document preparation on DocTrad; contains no model loading or network calls."""
from pathlib import Path

import pymupdf as fitz

from .extraction import extract
from .text_policy import sentence_parts


def import_document(store, path):
    path = Path(path)
    format_name = path.suffix.lower().lstrip('.')
    if format_name not in {'pdf', 'docx', 'pptx'}:
        raise ValueError('unsupported_document_format')
    data = path.read_bytes()
    ir = extract(data, format_name, tessdata='')
    original = store.put(data)
    pages = []
    if format_name == 'pdf':
        with fitz.open(stream=data, filetype='pdf') as pdf:
            for page in pdf:
                image = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                pages.append({'page': page.number, 'object': store.put(image.tobytes('png')),
                              'width_px': image.width, 'height_px': image.height, 'role': 'source_preview'})
    return store.put_json({'schema': 'doctrad-skynet-document-1', 'original': original,
                           'ir': ir.model_dump(), 'page_assets': pages,
                           'extraction': 'native_cpu', 'remote_inference_performed': False})


def translation_plan(store, document, max_source_characters=4000):
    if not 200 <= max_source_characters <= 16000:
        raise ValueError('invalid_source_character_budget')
    _, ir = store.document(document)
    units = []
    for node in ir.nodes:
        if not node.translatable:
            continue
        pieces, current = [], ''
        for sentence in sentence_parts(node.text):
            if len(sentence) > max_source_characters:
                # Do not cut technical references arbitrarily to satisfy an estimated budget.
                if current:
                    pieces.append(current)
                    current = ''
                pieces.append(sentence)
            elif current and len(current) + len(sentence) + 1 > max_source_characters:
                pieces.append(current)
                current = sentence
            else:
                current = (current + ' ' + sentence).strip()
        if current:
            pieces.append(current)
        siblings = [other for other in ir.nodes if node.parent and other.parent == node.parent]
        headers = [{'block_id': other.id, 'source': other.text} for other in siblings
                   if other.locator.get('row') == 0 or (other.locator.get('column') == 0
                   and other.locator.get('row') == node.locator.get('row'))]
        for index, piece in enumerate(pieces):
            units.append({'block_id': node.id, 'part': index, 'parts': len(pieces), 'source': piece,
                          'page': node.page, 'kind': node.kind,
                          'context': {'section': node.context.get('section', ''), 'table_headers': headers,
                                      'previous': node.context.get('previous', ''),
                                      'next': node.context.get('next', '')},
                          'needs_exact_tokenization': True,
                          'source_exceeds_character_budget': len(piece) > max_source_characters})
    return {'schema': 'doctrad-skynet-plan-1', 'document': document, 'units': units,
            'findings': [finding.model_dump() for finding in ir.findings],
            'requires_vision_pages': [page.number for page in ir.pages if page.scanned],
            'inference_performed': False, 'source_character_budget': max_source_characters}
