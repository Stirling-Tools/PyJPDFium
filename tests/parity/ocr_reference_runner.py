"""Runs the official PaddleOCR 3.7 pipeline (ONNX Runtime engine) on images, offline.

Usage: REFERENCE_PYTHON -I ocr_reference_runner.py PROFILE_DIR IMAGE [IMAGE ...]
Prints one JSON object per image. The models come from the profile directory, never from a hub.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def model_dir(profile: Path, work: Path, role: str, stem: str) -> Path:
    # PaddleOCR expects inference.onnx and inference.yml; link the pinned files under those names.
    target = work / role
    target.mkdir()
    (target / "inference.onnx").symlink_to(profile / f"{stem}.onnx")
    (target / "inference.yml").symlink_to(profile / f"{stem}.yml")
    return target


def pipeline_args(profile: Path) -> dict:
    """The profile's parameters as PaddleOCR arguments; one PaddleOCR cannot take is refused."""
    params = dict(line.split()[1:3] for line in (profile / "profile.txt").read_text().splitlines()
                  if line.startswith("param "))
    if params.get("det_max_side_limit", "4000") != "4000":
        raise SystemExit("PaddleOCR fixes det_max_side_limit at 4000")
    return {
        "text_det_limit_side_len": int(params["det_limit_side_len"]),
        "text_det_limit_type": params["det_limit_type"],
        "text_det_thresh": float(params["det_thresh"]),
        "text_det_box_thresh": float(params["det_box_thresh"]),
        "text_det_unclip_ratio": float(params["det_unclip_ratio"]),
        "text_recognition_batch_size": int(params["rec_batch_size"]),
    }


def main() -> None:
    profile, images = Path(sys.argv[1]), sys.argv[2:]
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["HF_HUB_OFFLINE"] = "1"
    from paddleocr import PaddleOCR

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        ocr = PaddleOCR(
            text_detection_model_name="PP-OCRv6_small_det",
            text_detection_model_dir=str(model_dir(profile, work, "det", "det")),
            text_recognition_model_name="PP-OCRv6_small_rec",
            text_recognition_model_dir=str(model_dir(profile, work, "rec", "rec")),
            engine="onnxruntime",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            **pipeline_args(profile),
        )
        for image in images:
            for res in ocr.predict(image):
                r = res.json["res"]
                print(json.dumps({
                    "image": image,
                    "polys": [[[int(v) for v in p] for p in poly] for poly in r["rec_polys"]],
                    "texts": r["rec_texts"],
                    "scores": [float(s) for s in r["rec_scores"]],
                }))


if __name__ == "__main__":
    main()
