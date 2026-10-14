"""Optional offline structural second opinion; never replaces native resource locators."""
from pathlib import Path
from .domain import Finding


def inspect_pdf(path: Path, artifacts_path: str):
    if not Path(artifacts_path).is_dir():
        raise ValueError("Local Docling models required")
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    options = PdfPipelineOptions(artifacts_path=Path(artifacts_path), do_ocr=False, enable_remote_services=False)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    result = converter.convert(path)
    return result.document.export_to_dict()


def compare(ir, semantic):
    text = " ".join(n.text for n in ir.nodes)
    texts = semantic.get("texts", [])
    missing = [item.get("text", "") for item in texts if item.get("text") and item["text"].strip() not in text]
    if missing:
        return [Finding(code="semantic_disagreement", severity="review", detail=f"Docling signale {len(missing)} régions à confronter à l’extraction native")]
    return []
