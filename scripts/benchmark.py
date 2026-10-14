#!/usr/bin/env python3
"""Reproducible extraction/reconstruction benchmark; real inference is never silently mocked."""
import argparse
import json
from pathlib import Path
import time
from doctrad2.extraction import extract
from doctrad2.reconstruction import build, validate_pdf
from doctrad2.storage import digest
from doctrad2.config import Settings
from doctrad2.inference import LlamaTranslator
from doctrad2.quality import check_text


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--translate", action="store_true", help="Use the configured resident BC-250 model")
    p.add_argument("--tessdata", default="")
    args = p.parse_args()
    source = args.source.read_bytes()
    started = time.monotonic()
    ir = extract(source, args.source.suffix[1:].lower(), args.tessdata)
    extracted = time.monotonic()
    translator = LlamaTranslator(Settings.load()) if args.translate else None
    targets, provenance = {}, {}
    try:
        for node in ir.nodes:
            if node.translatable:
                if translator:
                    targets[node.id], provenance[node.id] = translator.translate(node.text)
                else:
                    targets[node.id] = node.text
        translated = time.monotonic()
        output, report = build(source, ir, targets)
        for node in ir.nodes:
            if node.id in targets:
                report.findings.extend(check_text(node.text, targets[node.id], node.id) if translator else [])
        if ir.format == "pdf":
            validate_pdf(source, output, report)
    finally:
        if translator:
            translator.close()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / ("translated." + ir.format)).write_bytes(output)
    (args.output / "ir.json").write_text(ir.model_dump_json(indent=2))
    (args.output / "report.json").write_text(report.model_dump_json(indent=2))
    manifest = {"source_sha": digest(source), "mode": "real_bc250_translation" if translator else "source_identity_no_inference",
                "model": translator.contract.model_dump() if translator else None, "nodes": len(ir.nodes),
                "seconds": {"extraction": extracted - started, "translation": translated - extracted,
                            "reconstruction_qa": time.monotonic() - translated}, "quality_blocked": report.blocked}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
