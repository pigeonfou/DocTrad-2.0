from io import BytesIO
import html
import zipfile
from lxml import etree
import pymupdf as fitz
from .domain import QualityReport, Finding
from .extraction import xml_text_elements


def pdf_build(data, ir, translations):
    report = QualityReport(findings=list(ir.findings))
    masks = {}
    translated = 0
    with fitz.open(stream=data, filetype="pdf") as doc:
        for p in ir.pages:
            page = doc[p.number]
            page.set_rotation(0)
            original_links = page.get_links()
            nodes = [n for n in ir.nodes if n.page == p.number and n.translatable and n.id in translations]
            placements = []
            for node in nodes:
                target = translations[node.id]
                if target == node.text:
                    continue
                rotation = node.locator.get("text_rotation", 0)
                rect = fitz.Rect(node.bbox)
                if rect.is_empty or not page.rect.contains(rect):
                    report.findings.append(Finding(code="invalid_bounds", severity="critical", unit_id=node.id, detail="Zone source hors page"))
                    continue
                # Only remove original text after proving the French fits on a scratch page.
                size = max(1, min(r.size for r in node.runs)) if node.runs else 10
                color = node.runs[0].color if node.runs else 0
                others = [fitz.Rect(n.bbox) for n in ir.nodes if n.page == node.page and n.id != node.id and n.bbox]
                if node.kind == "table_cell" and "cell_bbox" in node.locator:
                    cell = fitz.Rect(node.locator["cell_bbox"])
                    rect = fitz.Rect(max(rect.x0, cell.x0 + 1), max(rect.y0, cell.y0 + 1), cell.x1 - 1, cell.y1 - 1)
                elif rotation == 0:
                    right = min(page.rect.x1 - 12, rect.x1 + max(size * 4, rect.width * .5))
                    for obstacle in others:
                        if obstacle.y0 < rect.y1 and obstacle.y1 > rect.y0 and obstacle.x0 >= rect.x1:
                            right = min(right, obstacle.x0 - 1)
                    extended = fitz.Rect(rect.x0, rect.y0, max(rect.x1, right), rect.y1 + size * .3)
                    if not any((extended & o).get_area() > .5 for o in others):
                        rect = extended
                style = f"body {{margin:0;padding:0;line-height:1.05;font-family:sans-serif;font-size:{size}pt;color:#{color:06x};}}"
                markup = "<div>" + html.escape(target).replace("\n", "<br>") + "</div>"
                probe = fitz.open()
                try:
                    scratch = probe.new_page(width=p.width, height=p.height)
                    spare, scale = scratch.insert_htmlbox(rect, markup, css=style, scale_low=.85, rotate=rotation)
                finally:
                    probe.close()
                if spare < 0:
                    report.findings.append(Finding(code="overflow", severity="critical", unit_id=node.id,
                                                   detail="Le français ne tient pas avec une réduction maximale de 15 %"))
                    continue
                if scale < .9:
                    report.findings.append(Finding(code="font_reduction", severity="review", unit_id=node.id,
                                                   detail=f"Échelle typographique {scale:.3f}"))
                if target != node.text:
                    other = [n for n in ir.nodes if n.page == node.page and n.id != node.id and n.bbox]
                    if any((rect & fitz.Rect(n.bbox)).get_area() > .5 for n in other):
                        report.findings.append(Finding(code="source_overlap", severity="critical", unit_id=node.id,
                                                       detail="La zone intersecte un autre bloc source"))
                        continue
                    placements.append((node, rect, markup, style, rotation))
            if not p.scanned:
                # Keep navigation out of the redaction pass: MuPDF otherwise deletes intersecting links.
                if placements:
                    for link in original_links:
                        page.delete_link(link)
                for node, rect, _, _, _ in placements:
                    # Character boxes rather than an expanded paragraph rectangle reduce collateral removals.
                    for run in node.runs:
                        page.add_redact_annot(fitz.Rect(run.bbox), fill=False, cross_out=False)
                if placements:
                    page.apply_redactions(images=0, graphics=0, text=0)
            for node, rect, markup, style, rotation in placements:
                if p.scanned:
                    # Image is preserved. White masking is explicitly non-certified for nonuniform backgrounds.
                    page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
                    report.findings.append(Finding(code="scan_mask", severity="review", unit_id=node.id,
                                                   detail="Masque blanc sur image : inspection obligatoire du fond et du schéma"))
                spare, scale = page.insert_htmlbox(rect, markup, css=style, scale_low=.85, rotate=rotation)
                if spare < 0:
                    report.findings.append(Finding(code="composition_failed", severity="critical", unit_id=node.id, detail="Échec de composition après simulation"))
                else:
                    translated += 1
                    masks.setdefault(p.number, []).append(tuple(rect))
            if placements and not p.scanned:
                for link in original_links:
                    page.insert_link({k: v for k, v in link.items() if k not in {"xref", "id"}})
            if len(page.get_images()) < p.images or len(page.get_drawings()) < p.drawings:
                report.findings.append(Finding(code="graphics_lost", severity="critical", detail=f"Page {p.number + 1}: ressource graphique perdue"))
            page.set_rotation(p.rotation)
        if doc.get_toc() != ir.navigation.get("toc", []):
            report.findings.append(Finding(code="bookmarks", severity="critical", detail="Signets modifiés"))
        result = doc.tobytes(garbage=3, deflate=True)
    # Redactions invalidate MuPDF's in-memory link xref cache. Inspect the serialized result.
    with fitz.open(stream=result, filetype="pdf") as reopened:
        if [len(page.get_links()) for page in reopened] != ir.navigation.get("links", []):
            report.findings.append(Finding(code="links", severity="critical", detail="Liens perdus ou ajoutés"))
    report.metrics = {"pages": len(ir.pages), "composed_units": translated, "native_graphics_preserved": not any(f.code == "graphics_lost" for f in report.findings),
                      "text_masks": masks, "font_policy": "local_html_fallback;max_15pct_reduction"}
    return result, report


def split_runs(target, source_texts):
    lengths = [len(t) for t in source_texts]
    total = max(1, sum(lengths))
    start = 0
    assigned = []
    for i, length in enumerate(lengths):
        if i == len(lengths) - 1:
            end = len(target)
        else:
            expected = round(len(target) * sum(lengths[:i + 1]) / total)
            spaces = [j + 1 for j in range(start, len(target)) if target[j].isspace()]
            end = min(spaces, key=lambda j: abs(j - expected)) if spaces else max(start, expected)
        assigned.append(target[start:end])
        start = end
    return assigned


def ooxml_build(data, ir, translations):
    mapping = {(n.locator["part"], n.locator["paragraph"]): n for n in ir.nodes}
    parts = {}
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for name, paragraph, _, _ in xml_text_elements(data, ir.format):
            if name not in parts:
                parts[name] = etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main" if ir.format == "docx" else "http://schemas.openxmlformats.org/drawingml/2006/main"
        for name, root in parts.items():
            for i, paragraph in enumerate(root.iter(f"{{{ns}}}p")):
                node = mapping.get((name, i))
                if not node or node.id not in translations:
                    continue
                texts = list(paragraph.iter(f"{{{ns}}}t"))
                assigned = split_runs(translations[node.id], [t.text or "" for t in texts])
                for elem, text in zip(texts, assigned):
                    elem.text = text
                    elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
            for item in archive.infolist():
                out.writestr(item, etree.tostring(parts[item.filename], xml_declaration=True, encoding="UTF-8", standalone=True)
                             if item.filename in parts else archive.read(item.filename))
    return output.getvalue(), QualityReport(findings=list(ir.findings), metrics={"units": len(translations), "run_mapping": "proportional_word_boundaries"})


def build(data, ir, translations):
    return pdf_build(data, ir, translations) if ir.format == "pdf" else ooxml_build(data, ir, translations)


def validate_pdf(source, target, report):
    with fitz.open(stream=source, filetype="pdf") as a, fitz.open(stream=target, filetype="pdf") as b:
        if len(a) != len(b):
            report.findings.append(Finding(code="page_count", severity="critical", detail="Nombre de pages modifié"))
            return report
        changed = 0
        checked = 0
        for i in range(len(a)):
            masks = [fitz.Rect(r) for r in report.metrics.get("text_masks", {}).get(i, report.metrics.get("text_masks", {}).get(str(i), []))]
            # Coarse raster inspection outside text masks supplements vector resource checks.
            pa = a[i].get_pixmap(matrix=fitz.Matrix(.5, .5), alpha=False)
            pb = b[i].get_pixmap(matrix=fitz.Matrix(.5, .5), alpha=False)
            if (pa.width, pa.height) != (pb.width, pb.height):
                report.findings.append(Finding(code="page_geometry", severity="critical", detail=f"Dimensions page {i + 1} modifiées"))
                continue
            sa, sb = pa.samples, pb.samples
            for y in range(0, pa.height, 2):
                for x in range(0, pa.width, 2):
                    if any((r + (-3, -3, 3, 3)).contains(fitz.Point(x * 2, y * 2)) for r in masks):
                        continue
                    offset = (y * pa.width + x) * pa.n
                    checked += 1
                    changed += int(any(abs(sa[offset + c] - sb[offset + c]) > 20 for c in range(3)))
        ratio = changed / max(1, checked)
        report.metrics["outside_text_pixel_change_ratio"] = ratio
        if ratio > .001:
            report.findings.append(Finding(code="outside_text_visual_change", severity="critical", detail="Différence visuelle hors des zones textuelles"))
    return report
