from io import BytesIO
import re
import math
import pymupdf as fitz
from docx import Document as WordDocument
from pptx import Presentation
from .domain import DocumentIR, Node, Run, Page, Finding
from .storage import digest, key


def node_id(source_sha, locator):
    return key([source_sha, "native-2.1.0", locator])


def extract_pdf(data, tessdata=""):
    ir = DocumentIR(source_sha=digest(data), format="pdf")
    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.is_encrypted:
            raise ValueError("encrypted_pdf")
        if doc.page_count > 500:
            raise ValueError("too_many_pages")
        ir.navigation = {"toc": doc.get_toc(), "links": [len(p.get_links()) for p in doc]}
        section = ""
        for page in doc:
            number = page.number
            original_rotation = page.rotation
            page.set_rotation(0)
            native = page.get_text("dict")
            spans = [s for b in native["blocks"] if b["type"] == 0 for line in b["lines"] for s in line["spans"]]
            native_chars = sum(len(s["text"].strip()) for s in spans)
            image_blocks = [b for b in native["blocks"] if b["type"] == 1]
            image_coverage = sum(fitz.Rect(b["bbox"]).get_area() for b in image_blocks) / max(1, page.rect.get_area())
            scanned = native_chars < 30 and image_coverage > .4
            engine = "native"
            if scanned:
                if not tessdata:
                    ir.findings.append(Finding(code="ocr_required", severity="critical", detail=f"Page {number + 1}: OCR local non configuré"))
                    spans = []
                    native = {"blocks": []}
                else:
                    textpage = page.get_textpage_ocr(language="eng", dpi=300, full=True, tessdata=tessdata)
                    native = page.get_text("dict", textpage=textpage)
                    engine = "tesseract"
                    ir.findings.append(Finding(code="scan_review", severity="review", detail=f"Page {number + 1}: vérifier l’OCR et l’effacement des zones"))
            elif image_coverage > .4:
                ir.findings.append(Finding(code="mixed_page", severity="review", detail=f"Page {number + 1}: vérifier le texte dans les images"))
            ir.pages.append(Page(number=number, width=page.rect.width, height=page.rect.height,
                                 rotation=original_rotation, cropbox=list(page.cropbox), images=len(page.get_images()),
                                 drawings=len(page.get_drawings()), scanned=scanned))
            cells = []
            if not scanned and not page.rotation:
                try:
                    tables = page.find_tables()
                    for ti, table in enumerate(tables.tables):
                        table_area = fitz.Rect(table.bbox).get_area() / max(1, page.rect.get_area())
                        if table_area > .6 and table.row_count < 4:
                            ir.findings.append(Finding(code="table_candidate_rejected", severity="review", detail=f"Page {number + 1}: grande zone avec trop peu de lignes, extraction native conservée"))
                            continue
                        for row, line in enumerate(table.rows):
                            for column, cell in enumerate(line.cells):
                                if cell:
                                    cells.append((fitz.Rect(cell), f"table-{number}-{ti}", row, column))
                except (RuntimeError, ValueError):
                    ir.findings.append(Finding(code="table_detection", severity="review", detail=f"Page {number + 1}: détection des tableaux non concluante"))
            groups = {}
            for bi, block in enumerate(native["blocks"]):
                if block["type"] != 0:
                    continue
                for li, line in enumerate(block["lines"]):
                    runs = [Run(text=s["text"], bbox=s["bbox"], font=s["font"], size=s["size"],
                                color=s["color"], flags=s["flags"], origin=s.get("origin")) for s in line["spans"] if s["text"].strip()]
                    if not runs:
                        continue
                    bbox = fitz.Rect(line["bbox"])
                    hit = next((c for c in cells if c[0].contains((bbox.tl + bbox.br) / 2)), None)
                    if hit and not (hit[0] + (-1, -1, 1, 1)).contains(bbox):
                        # Background artwork may produce phantom columns inside a label.
                        # Merge only adjacent cells of this row touched by the source line.
                        touched = [c for c in cells if c[1:3] == hit[1:3] and (c[0] & bbox).get_area() > 0]
                        merged = fitz.Rect(hit[0])
                        for candidate in touched:
                            merged |= candidate[0]
                        hit = (merged, *hit[1:]) if (merged + (-1, -1, 1, 1)).contains(bbox) else None
                    locator = {"page": number, "block": bi, "line": li}
                    direction = line.get("dir", (1, 0))
                    angle = (-math.degrees(math.atan2(direction[1], direction[0]))) % 360
                    cardinal = min((0, 90, 180, 270, 360), key=lambda a: abs(a - angle))
                    locator["text_rotation"] = cardinal % 360
                    locator["text_angle"] = round(angle, 4)
                    gkey = (hit[1], hit[2], hit[3]) if hit else (bi, cardinal)
                    group = groups.setdefault(gkey, {"runs": [], "lines": [], "boxes": [], "locator": locator,
                                                    "hit": hit, "rotated": False, "aligned_boxes": []})
                    for span in line['spans']:
                        if span['text'].strip():
                            quad = fitz.recover_quad(direction, span)
                            points = [point * fitz.Matrix(angle) for point in quad]
                            group['aligned_boxes'].append(fitz.Rect(min(p.x for p in points), min(p.y for p in points),
                                                                   max(p.x for p in points), max(p.y for p in points)))
                    group["runs"].extend(runs)
                    group["lines"].append("".join(r.text for r in runs))
                    group["boxes"].append(bbox)
                    group["rotated"] |= abs(cardinal - angle) > 1
            for group in groups.values():
                text = "\n".join(group["lines"])
                bbox = fitz.Rect(group["boxes"][0])
                for rect in group["boxes"][1:]:
                    bbox |= rect
                hit = group["hit"]
                locator = group["locator"] | ({"row": hit[2], "column": hit[3], "table": hit[1], "cell_bbox": list(hit[0])} if hit else {})
                if group['rotated'] and group['aligned_boxes']:
                    aligned = fitz.Rect(group['aligned_boxes'][0])
                    for box in group['aligned_boxes'][1:]:
                        aligned |= box
                    locator['aligned_size'] = [aligned.width, aligned.height]
                nid = node_id(ir.source_sha, locator)
                sizes = [r.size for r in group["runs"]]
                if not hit and len(text) < 120 and max(sizes) > 13:
                    section = text
                ir.nodes.append(Node(id=nid, page=number, text=text, bbox=tuple(bbox), runs=group["runs"],
                                     kind="table_cell" if hit else "paragraph", parent=hit[1] if hit else None,
                                     locator=locator, context={"section": section}, engine=engine,
                                     translatable=True))
                if group["rotated"]:
                    ir.findings.append(Finding(code="rotated_text", severity="review", unit_id=nid,
                                               detail="Texte incliné recomposé vectoriellement : vérifier orientation et espacement"))
            page.set_rotation(original_rotation)
        if len(ir.nodes) > 20000:
            raise ValueError("too_many_units")
        native_count = sum(len(n.text) for n in ir.nodes)
        if not native_count:
            ir.findings.append(Finding(code="empty_extraction", severity="critical", detail="Aucun texte extrait"))
    return contextualize(ir)


def xml_text_elements(data, fmt):
    # Locator is the paragraph XML order; all original runs/resources stay in the package.
    import zipfile
    from lxml import etree
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main" if fmt == "docx" else "http://schemas.openxmlformats.org/drawingml/2006/main"
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = sorted(name for name in archive.namelist() if
                       (fmt == "docx" and re.fullmatch(r"word/(document|header\d+|footer\d+)\.xml", name)) or
                       (fmt == "pptx" and re.fullmatch(r"ppt/slides/slide\d+\.xml", name)))
        for name in names:
            root = etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
            for i, paragraph in enumerate(root.iter(f"{{{ns}}}p")):
                texts = list(paragraph.iter(f"{{{ns}}}t"))
                text = "".join(t.text or "" for t in texts)
                if text.strip():
                    yield name, i, text, texts


def extract_ooxml(data, fmt):
    # Validate format with its native reader before traversing package XML.
    (WordDocument if fmt == "docx" else Presentation)(BytesIO(data))
    ir = DocumentIR(source_sha=digest(data), format=fmt)
    for part, paragraph, text, _ in xml_text_elements(data, fmt):
        locator = {"part": part, "paragraph": paragraph}
        ir.nodes.append(Node(id=node_id(ir.source_sha, locator), page=0, text=text, locator=locator, engine="ooxml"))
    ir.findings.append(Finding(code="ooxml_pagination", severity="review", detail="Vérifier pagination et styles avec le moteur bureautique local"))
    return contextualize(ir)


def contextualize(ir):
    for i, node in enumerate(ir.nodes):
        node.context |= {"previous": ir.nodes[i - 1].text[:300] if i else "",
                         "next": ir.nodes[i + 1].text[:300] if i + 1 < len(ir.nodes) else ""}
        if node.parent:
            siblings = [n for n in ir.nodes if n.parent == node.parent]
            node.context["table_headers"] = [n.text for n in siblings if n.locator.get("row") == 0]
    return ir


def extract(data, fmt, tessdata=""):
    return extract_pdf(data, tessdata) if fmt == "pdf" else extract_ooxml(data, fmt)
