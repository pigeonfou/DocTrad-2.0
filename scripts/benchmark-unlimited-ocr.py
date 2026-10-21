#!/usr/bin/env python3
"""Offline OCR benchmark on public fixtures, with source-derived accuracy metrics."""
import argparse
from collections import Counter
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import unicodedata

SOURCE_HASHES = {
    "40e3d24478e8ae219039c505f3faa3b0de6d5962c3f738d323f8b4a48146f2b2",
    "cc6a5ca2bd9fad41fce19136afd7aaca3315a783a52348a4984bf11d8b8e41f6",
}


class TableText(HTMLParser):
    """Keep HTML cell boundaries without counting markup as recognized text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in {"td", "th", "tr", "table", "br", "p"}:
            self.parts.append("\n" if tag in {"tr", "table", "p", "br"} else "\t")
    def handle_endtag(self, tag):
        if tag in {"td", "th", "tr", "table", "p"}:
            self.parts.append("\n" if tag in {"tr", "table", "p"} else "\t")
    def handle_data(self, data):
        self.parts.append(data)


def clean_output(text):
    text = re.sub(r"<\|det\|>.*?<\|/det\|>", "", text, flags=re.S)
    # A leading opening token can be omitted by the CLI; require its closing marker.
    text = re.sub(r"(?m)^[ \t]*[A-Za-z_][\w-]*[ \t]*\[[0-9., \t+-]+\][ \t]*<\|/det\|>", "", text)
    text = re.sub(r"<\|/?(?:ref|grounding)\|>", "", text)
    for token in ("<｜end▁of▁sentence｜>", "<｜begin▁of▁sentence｜>", "<｜▁pad▁｜>"):
        text = text.replace(token, "")
    parser = TableText()
    parser.feed(text)
    return "".join(parser.parts).strip()


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).replace("−", "-").replace("’", "'").casefold().split())


def accuracy(source, target):
    left, right = normalize(source), normalize(target)
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        new = [i]
        for j, b in enumerate(right, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = new
    words = lambda s: Counter(re.findall(r"\w+(?:[-']\w+)*", s))
    expected, actual = words(left), words(right)
    matched = sum((expected & actual).values())
    numbers = lambda s: Counter(re.findall(r"(?<!\w)-?\d+(?:[.,]\d+)?", s))
    return {"cer": round(row[-1] / max(1, len(left)), 5),
            "word_recall": round(matched / max(1, sum(expected.values())), 5),
            "word_precision": round(matched / max(1, sum(actual.values())), 5),
            "source_numbers": dict(numbers(left)), "recognized_numbers": dict(numbers(right)),
            "numbers_preserved": numbers(left) == numbers(right)}


def prepare(directory, source_pdf, min_long_edge=0, reference_only=False, render_scale=2, tile_grid=1, page_limit=0, text_regions=False):
    import pymupdf as fitz
    if hashlib.sha256(source_pdf.read_bytes()).hexdigest() not in SOURCE_HASHES:
        raise SystemExit("Only the pinned public reference is permitted")
    directory.mkdir(parents=True, exist_ok=False)
    text_lines = [
        "DOCTRAD OCR VALIDATION",
        "Input voltage: 12 V.",
        "Operating temperature: -20 to 55 degrees Celsius.",
        "Do not disconnect the protective earth conductor.",
        "The compact recorder supports two synchronized channels.",
    ]
    document = fitz.open()
    page = document.new_page(width=600, height=360)
    for index, text in enumerate(text_lines):
        page.insert_text((30, 55 + 54 * index), text, fontsize=19 if index == 0 else 15, fontname="helv")
    fixtures = []
    for label, scale in (("clean-single-view", 1), ("clean-multi-view", 2)):
        name = label + ".png"
        page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(directory / name)
        fixtures.append({"name": label, "image": name, "source": "\n".join(text_lines)})
    with fitz.open(source_pdf) as reference:
        for page in reference:
            if page_limit and page.number >= page_limit:
                break
            name = f"technical-reference-{page.number + 1}.png"
            page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False).save(directory / name)
            fixtures.append({"name": f"technical-reference-{page.number + 1}",
                             "image": name, "source": page.get_text(sort=False)})
            if text_regions:
                for bi, block in enumerate(page.get_text("dict")["blocks"]):
                    if block["type"] != 0:
                        continue
                    spans = [span for line in block["lines"] for span in line["spans"]]
                    if not spans:
                        continue
                    rotated = any(abs(line["dir"][1]) > .02 for line in block["lines"])
                    if min(span["size"] for span in spans) > 8 and not rotated:
                        continue
                    clip = (fitz.Rect(block["bbox"]) + (-3, -3, 3, 3)) & page.rect
                    scale = max(render_scale, 1000 / max(clip.width, clip.height))
                    direction = block["lines"][0]["dir"]
                    angle = -math.degrees(math.atan2(direction[1], direction[0]))
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale).prerotate(angle), clip=clip, alpha=False)
                    canvas = fitz.open()
                    region_page = canvas.new_page(width=max(1200, pix.width+100), height=max(720, pix.height+100))
                    x, y = (region_page.rect.width-pix.width)/2, (region_page.rect.height-pix.height)/2
                    region_page.insert_image(fitz.Rect(x,y,x+pix.width,y+pix.height), pixmap=pix)
                    label = f"technical-reference-{page.number+1}-region-{bi}"
                    region_page.get_pixmap(alpha=False).save(directory / (label+".png"))
                    canvas.close()
                    fixtures.append({"name": label, "image": label+".png",
                                     "source": "\n".join("".join(span["text"] for span in line["spans"]) for line in block["lines"]),
                                     "clip": list(clip), "diagnostic_native_region": True})
                fixtures = [f for f in fixtures if f["name"] != f"technical-reference-{page.number+1}"]
            if tile_grid > 1:
                for row in range(tile_grid):
                    for col in range(tile_grid):
                        w, h = page.rect.width / tile_grid, page.rect.height / tile_grid
                        clip = fitz.Rect(max(0, col*w-w*.1), max(0, row*h-h*.1),
                                         min(page.rect.width, (col+1)*w+w*.1),
                                         min(page.rect.height, (row+1)*h+h*.1))
                        label = f"technical-reference-{page.number + 1}-tile-{row}-{col}"
                        page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), clip=clip, alpha=False).save(directory / (label+".png"))
                        fixtures.append({"name": label, "image": label+".png",
                                         "source": page.get_text(clip=clip, sort=False),
                                         "clip": list(clip), "diagnostic_tile": True})
                fixtures = [f for f in fixtures if f["name"] != f"technical-reference-{page.number + 1}"]

    if reference_only:
        fixtures = [item for item in fixtures if item["name"].startswith("technical-reference-")]
    for fixture in fixtures:
        path = directory / fixture["image"]
        pixmap = fitz.Pixmap(path)
        fixture["original_size"] = [pixmap.width, pixmap.height]
        scale = max(1.0, min_long_edge / max(pixmap.width, pixmap.height))
        if scale > 1:
            pixmap = fitz.Pixmap(pixmap, round(pixmap.width * scale), round(pixmap.height * scale), None)
            pixmap.save(path)
        fixture["input_size"] = [pixmap.width, pixmap.height]
    (directory / "fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=2))
    print("PUBLIC_OCR_FIXTURES=" + json.dumps(fixtures, ensure_ascii=False))


def run(args):
    directory = args.directory
    fixtures = json.loads((directory / "fixtures.json").read_text())
    lock_path = Path.home() / ".cache/doctrad2/ocr-test.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for entry in Path("/proc").glob("[0-9]*"):
            try:
                if Path(os.readlink(entry / "exe")).name in {"llama-server", "llama-cli", "llama-mtmd-cli"}:
                    raise SystemExit("Another inference process is active")
            except (OSError, PermissionError):
                pass
        results = []
        for fixture in fixtures:
            label = fixture["name"]
            command = [str(args.binary), "-m", str(args.model), "--mmproj", str(args.projector),
                       "--image", str(directory / fixture["image"]), "-p", args.prompt,
                       "--chat-template", "deepseek-ocr", "--no-jinja",
                       "--device", "Vulkan0", "--n-gpu-layers", "99", "--flash-attn", "off",
                       "--no-warmup", "--temp", "0", "--repeat-penalty", "1.0",
                       "--override-kv", "deepseek2-ocr.attention.sliding_window=int:128",
                       "--cache-type-v", "f32", "-c", str(args.context), "-n", str(args.predict),
                       "-b", "512", "-ub", "128",
                       "--dry-multiplier", "0.8", "--dry-base", "1.75", "--dry-allowed-length", "35",
                       "--dry-penalty-last-n", "128", "--dry-sequence-breaker", "none"]
            if args.vision_cpu:
                command.append("--no-mmproj-offload")
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = str(args.binary.parent)
            started = time.monotonic()
            with (directory / (label + ".txt")).open("wb") as stdout, (directory / (label + ".log")).open("wb") as stderr:
                try:
                    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                            timeout=300, start_new_session=True, env=env, check=False)
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    code = 124
            raw = (directory / (label + ".txt")).read_text(errors="replace")
            log = (directory / (label + ".log")).read_text(errors="replace")
            target = clean_output(raw)
            finish = re.search(r"DOCTRAD_OCR_FINISH tokens=(\d+) eog=([01])", log)
            metrics = accuracy(fixture["source"], target)
            item = {"case": label, "returncode": code, "seconds": round(time.monotonic() - started, 3),
                    "tokens": int(finish[1]) if finish else None,
                    "ended_eog": bool(finish and finish[2] == "1"),
                    "recognized_characters": len(target), **metrics, "source": fixture["source"], "recognized": target,
                    "profile": {"prompt": args.prompt, "vision_cpu": args.vision_cpu,
                                "projector": str(args.projector), "context": args.context, "predict": args.predict},
                    "diagnostic_native_region": fixture.get("diagnostic_native_region", False),
                    "input_size": fixture.get("input_size"), "clip": fixture.get("clip")}
            item["passed"] = (code == 0 and item["ended_eog"] and bool(target)
                              and metrics["word_recall"] >= .95 and metrics["word_precision"] >= .95
                              and metrics["numbers_preserved"])
            results.append(item)
            (directory / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
            print("PUBLIC_OCR_BENCHMARK=" + json.dumps(item, ensure_ascii=False), flush=True)
            if code:
                print("OCR_FAILURE_LOG=" + log[-2500:], flush=True)
        print("PUBLIC_OCR_SUMMARY=" + json.dumps({"passed": sum(r["passed"] for r in results),
                                                  "total": len(results), "directory": str(directory)}), flush=True)
        return 0 if all(r["passed"] for r in results) else 65


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--source-pdf", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--projector", type=Path)
    parser.add_argument("--reference-only", action="store_true")
    parser.add_argument("--min-long-edge", type=int, default=0)
    parser.add_argument("--text-regions", action="store_true")
    parser.add_argument("--tile-grid", type=int, choices=(1, 2), default=1)
    parser.add_argument("--page-limit", type=int, default=0)
    parser.add_argument("--render-scale", type=float, default=2)
    parser.add_argument("--vision-cpu", action="store_true")
    parser.add_argument("--prompt", default="document parsing.")
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--predict", type=int, default=2400)
    args = parser.parse_args()
    if args.prepare:
        if not args.source_pdf:
            parser.error("--source-pdf is required for fixture preparation")
        prepare(args.directory, args.source_pdf, args.min_long_edge, args.reference_only, args.render_scale, args.tile_grid, args.page_limit, args.text_regions)
        return 0
    for key in ("binary", "model", "projector"):
        if getattr(args, key) is None:
            parser.error("--" + key + " is required for inference")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
