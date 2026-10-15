from io import BytesIO
import zipfile
from lxml import etree
import pymupdf as fitz
from .domain import QualityReport, Finding
from .extraction import xml_text_elements
from .layout import placement_box, text_markup, COMPOSITION_VERSION
from .quality import QUALITY_VERSION


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
                angle = node.locator.get('text_angle', rotation)
                angled = abs((angle - rotation + 180) % 360 - 180) > 1
                angle_pdf = None
                rect = fitz.Rect(node.bbox)
                if rect.is_empty or not page.rect.contains(rect):
                    report.findings.append(Finding(code="invalid_bounds", severity="critical", unit_id=node.id, detail="Zone source hors page"))
                    continue
                page_nodes = [n for n in ir.nodes if n.page == node.page]
                rect = placement_box(node, page, page_nodes)
                markup, style = text_markup(node, target)
                # A second translated block may already occupy otherwise blank space.
                if any((rect & placed[1]).get_area() > .5 for placed in placements):
                    rect = fitz.Rect(node.bbox)
                if angled and node.locator.get('aligned_size'):
                    width, height = node.locator['aligned_size']
                    probe = fitz.open()
                    scratch = probe.new_page(width=max(1, width), height=max(1, height + 2))
                    spare, scale = scratch.insert_htmlbox(scratch.rect, markup, css=style, scale_low=.85)
                    if spare >= 0:
                        angle_pdf = probe.tobytes()
                    probe.close()
                    if angle_pdf is None:
                        report.findings.append(Finding(code='overflow', severity='critical', unit_id=node.id,
                                                       detail='Le texte incliné ne tient pas dans son cadre'))
                        continue
                    if any((rect & placed[1]).get_area() > .5 for placed in placements):
                        report.findings.append(Finding(code='source_overlap', severity='critical', unit_id=node.id,
                                                       detail='La zone inclinée intersecte un bloc traduit'))
                        continue
                    placements.append((node, rect, markup, style, angle, angle_pdf))
                    continue
                probe = fitz.open()
                try:
                    scratch = probe.new_page(width=p.width, height=p.height)
                    spare, scale = scratch.insert_htmlbox(rect, markup, css=style, scale_low=.85, rotate=rotation)
                    if spare >= 0 and not rotation and node.kind != 'table_cell' and node.runs and node.runs[0].origin:
                        spans = [s for block in scratch.get_text('dict')['blocks'] if block['type'] == 0
                                 for line in block['lines'] for s in line['spans']]
                        if spans:
                            delta = node.runs[0].origin[1] - spans[0]['origin'][1]
                            if 0 < delta < node.runs[0].size and rect.height - delta > node.runs[0].size:
                                rect = rect + (0, delta, 0, 0)
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
                    placements.append((node, rect, markup, style, rotation, None))
            if not p.scanned:
                # Keep navigation out of the redaction pass: MuPDF otherwise deletes intersecting links.
                if placements:
                    for link in original_links:
                        page.delete_link(link)
                for node, rect, _, _, _, _ in placements:
                    # Character boxes rather than an expanded paragraph rectangle reduce collateral removals.
                    for run in node.runs:
                        page.add_redact_annot(fitz.Rect(run.bbox), fill=False, cross_out=False)
                if placements:
                    page.apply_redactions(images=0, graphics=0, text=0)
            for node, rect, markup, style, rotation, angle_pdf in placements:
                if p.scanned:
                    # Image is preserved. White masking is explicitly non-certified for nonuniform backgrounds.
                    page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
                    report.findings.append(Finding(code="scan_mask", severity="review", unit_id=node.id,
                                                   detail="Masque blanc sur image : inspection obligatoire du fond et du schéma"))
                if angle_pdf is not None:
                    with fitz.open(stream=angle_pdf, filetype='pdf') as angled_page:
                        page.show_pdf_page(rect, angled_page, rotate=rotation, keep_proportion=True)
                    spare = 0
                else:
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
    report.metrics = {"composition_version": COMPOSITION_VERSION, "quality_version": QUALITY_VERSION, "pages": len(ir.pages), "composed_units": translated, "native_graphics_preserved": not any(f.code == "graphics_lost" for f in report.findings),
                      "text_masks": masks, "font_policy": "weighted_source_style;bounded_columns;max_15pct_reduction"}
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
