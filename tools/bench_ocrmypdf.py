"""Benchmarks OCRmyPDF with Tesseract against OCRmyPDF with the pyjpdfium plugin.

  python tools/bench_ocrmypdf.py OCRMYPDF_PYTHON WORK_DIR [--pages N] [--jobs 1,8]
      [--variant "LABEL|EXTRA OCRMYPDF ARGS" ...]

Generates scanned pages of seeded English text in three base-14 fonts, so the ground truth is
known. It then runs each engine's real OCRmyPDF command line, and reports for each run:

- wall and CPU time, and the peak RSS of any one process;
- character and word error rates of the text that PDFium extracts from the output.

Needs Tesseract with English data for the Tesseract runs, and PYJPDFIUM_OCR_PROFILE.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import zlib
from pathlib import Path

import pyjpdfium

WORDS = (
    "the of and to in is was for that with as on by at from his her are were this which be or "
    "an have had not but they all one their there been has more when who will would other into "
    "time only new some could these two may first then do any like my now over such our man me "
    "even most made after also did many before must through back years where much your way well "
    "down should because each just those people how too little state good very make world still "
    "own see men work long get here between both life being under never day same another know "
    "while last might us great old year off come since against go came right used take three "
    "invoice account payment balance report total amount number date order customer service "
    "quarter annual review budget meeting schedule project office address request policy"
).split()
FONTS = ("Helvetica", "Times-Roman", "Courier")


def page_lines(rng: random.Random, count: int) -> list[str]:
    lines = []
    for _ in range(count):
        words = [rng.choice(WORDS) for _ in range(rng.randint(6, 10))]
        if rng.random() < 0.3:
            words.insert(rng.randrange(len(words)), str(rng.randint(10, 99999)))
        words[0] = words[0].capitalize()
        lines.append(" ".join(words) + rng.choice([".", ",", "", ":"]))
    return lines


def pdf(pages: list[tuple[str, str, bytes | None]]) -> bytes:
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for extra, content, image in pages:
        number = len(objects) + 1
        kids.append(f"{number} 0 R")
        resources = f"/Resources << /XObject << /Im0 {number + 2} 0 R >> >>" if image else ""
        objects.append(f"<< /Type /Page /Parent 2 0 R {extra} {resources} "
                       f"/Contents {number + 1} 0 R >>".encode())
        data = content.encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
        if image:
            objects.append(image)
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out, offsets = bytearray(b"%PDF-1.7\n"), []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1,
                                                                               xref)
    return bytes(out)


def corpus(work: Path, pages: int) -> tuple[Path, list[str]]:
    rng = random.Random(20261011)
    truth, scanned = [], []
    for index in range(pages):
        font, size = FONTS[index % len(FONTS)], 11 + index % 3
        lines = page_lines(rng, 34)
        content = "".join(f"BT /F1 {size} Tf 60 {740 - 20 * i} Td ({line}) Tj ET "
                          for i, line in enumerate(lines))
        resources = (f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
                     f"/BaseFont /{font} >> >> >>")
        source = work / f"source-{index}.pdf"
        source.write_bytes(pdf([(f"/MediaBox [0 0 612 792] {resources}", content, None)]))
        png = work / f"scan-{index}.png"
        pyjpdfium.rasterize_page(source, 0, png, device="pnggray", raster_dpi=300)
        with pyjpdfium.load_image(png) as bitmap:
            raw = bitmap.tobytes()
            gray = raw[0::3] if bitmap.pixel_format.name == "RGB8" else raw
            width, height = bitmap.width, bitmap.height
        data = zlib.compress(gray)
        image = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace "
                 b"/DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\n"
                 b"stream\n" % (width, height, len(data)) + data + b"\nendstream")
        scanned.append(("/MediaBox [0 0 612 792]", "q 612 0 0 792 0 0 cm /Im0 Do Q", image))
        truth.append(" ".join(lines))
    path = work / "scanned.pdf"
    path.write_bytes(pdf(scanned))
    return path, truth


def distance(a: list, b: list) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        current = [i]
        for j, y in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def accuracy(output: Path, truth: list[str]) -> tuple[float, float]:
    chars = words = char_errors = word_errors = 0
    with pyjpdfium.open_document(output) as document:
        for index, expected in enumerate(truth):
            with document.page(index) as page:
                got = " ".join(page.text().split())
            char_errors += distance(list(got), list(expected))
            word_errors += distance(got.split(), expected.split())
            chars += len(expected)
            words += len(expected.split())
    return char_errors / chars, word_errors / words


MEASURE = r"""
import json, resource, subprocess, sys, time
start = time.perf_counter()
done = subprocess.run(sys.argv[1:], capture_output=True, text=True)
wall = time.perf_counter() - start
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
print(json.dumps({"rc": done.returncode, "wall": wall, "cpu": usage.ru_utime + usage.ru_stime,
                  "rss_mib": usage.ru_maxrss / 1024, "stderr": done.stderr[-2000:]}))
"""


def run(python: str, args: list[str]) -> dict:
    done = subprocess.run([sys.executable, "-c", MEASURE, python, "-m", "ocrmypdf", *args],
                          capture_output=True, text=True, check=True)
    result = json.loads(done.stdout)
    if result["rc"] != 0:
        raise SystemExit(f"ocrmypdf {' '.join(args)} failed:\n{result['stderr']}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("python")
    parser.add_argument("work", type=Path)
    parser.add_argument("--pages", type=int, default=12)
    parser.add_argument("--jobs", default="1,8")
    parser.add_argument("--variant", action="append", default=[],
                        help="LABEL|ARGS; the default compares Tesseract with the plugin")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    source, truth = corpus(args.work, args.pages)
    variants = args.variant or ["tesseract|", "pyjpdfium|--plugin pyjpdfium.ocrmypdf"]
    engines = {}
    for variant in variants:
        label, _, extra = variant.partition("|")
        engines[label] = ["--output-type", "pdf", *extra.split()]
    results = []
    for jobs in (int(j) for j in args.jobs.split(",")):
        for name, engine_args in engines.items():
            out = args.work / f"{name}-{jobs}.pdf"
            measured = run(args.python, [*engine_args, "--jobs", str(jobs), str(source), str(out)])
            cer, wer = accuracy(out, truth)
            row = {"engine": name, "jobs": jobs, "pages": args.pages,
                   "wall_s": round(measured["wall"], 2),
                   "s_per_page": round(measured["wall"] / args.pages, 3),
                   "cpu_s": round(measured["cpu"], 1), "peak_rss_mib": round(measured["rss_mib"]),
                   "cer": round(cer, 4), "wer": round(wer, 4)}
            results.append(row)
            print(json.dumps(row), flush=True)
    (args.work / "results.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
