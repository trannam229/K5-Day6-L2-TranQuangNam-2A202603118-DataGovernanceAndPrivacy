"""T14 pipeline tests (Member 4 — QA / Metric). End-to-end contract + failure / edge cases.

Unit tests for the algorithm itself live in tests/test_t14_processor.py; this file checks the
5-step pipeline (src/pipeline.py) the way the lab runs it. No ground truth needed.
"""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import main as runner
from src import pipeline
from src.common.context import RunContext
from src.t14_processor import LabelMapError

FX = Path("fixtures/t14_auto_annotation")
TAXONOMY = {"car", "pedestrian", "motorbike", "sign"}


def _run(out):
    return runner.main(["--track", "t14", "--config", "configs/lab.yaml", "--output", str(out),
                        "--offline", "--seed", "42"])


def _ctx(tmp_path, input_dir=FX, **config):
    return RunContext(track="t14", input_dir=Path(input_dir), output_dir=tmp_path, config=config,
                      seed=42, rng=np.random.default_rng(42))


# ---------------------------------------------------------------- success case
def test_pipeline_end_to_end_schema_taxonomy_and_bounds(tmp_path):
    out = tmp_path / "poc"
    assert _run(out) == 0

    pred = pd.read_csv(out / "predictions.csv")
    assert list(pred.columns[:7]) == ["image_id", "class", "x", "y", "w", "h", "conf"]
    assert len(pred) > 0 and set(pred["class"]) <= TAXONOMY          # names, never raw model ids

    sizes = pd.read_csv(FX / "images.csv").set_index("image_id")
    assert set(pred["image_id"]) <= set(sizes.index)
    W, H = pred["image_id"].map(sizes["width"]), pred["image_id"].map(sizes["height"])
    assert (pred.w > 0).all() and (pred.h > 0).all() and (pred.x >= 0).all() and (pred.y >= 0).all()
    assert (pred.x + pred.w <= W + 0.5).all() and (pred.y + pred.h <= H + 0.5).all()   # invalid-label rate = 0

    queue = pd.read_csv(out / "review_queue.csv")
    assert len(queue) == 30 and queue["score"].is_monotonic_decreasing               # budget B = 30

    decision = json.loads((out / "decision.json").read_text(encoding="utf-8"))
    assert decision["status"] in {"GO", "HOLD", "REWORK"} and decision["owner"] and decision["reason_code"]
    for f in ["audit_log.jsonl", "export/annotations_coco.json", "export/classes.txt", "export/qa_report.json"]:
        assert (out / f).exists(), f


def test_pipeline_is_reproducible_with_same_seed(tmp_path):
    assert _run(tmp_path / "a") == 0 and _run(tmp_path / "b") == 0
    for f in ["predictions.csv", "review_queue.csv"]:
        assert (tmp_path / "a" / f).read_text() == (tmp_path / "b" / f).read_text(), f


# ---------------------------------------------------------------- edge cases
def test_out_of_bounds_boxes_are_clipped_not_exported_raw(tmp_path):
    ctx = _ctx(tmp_path)
    data = pipeline.load(ctx)
    iid = data["images"]["image_id"].iloc[0]
    data["predictions"] = pd.DataFrame({
        "image_id": [iid, iid, iid], "class_id": [2, 0, 11],
        "x": [-10.0, 300.0, 400.0], "y": [50.0, 170.0, 10.0], "w": [40.0, 50.0, 20.0], "h": [30.0, 30.0, 20.0],
        "conf": [0.9, 0.9, 0.9]})
    out = pipeline.process(ctx, data)
    assert len(out) == 2                                              # box fully outside the image is dropped
    assert (out.x >= 0).all() and (out.x + out.w <= 320).all() and (out.y + out.h <= 180).all()
    assert out["was_clipped"].all()


def test_unknown_model_class_id_fails_loudly(tmp_path):
    ctx = _ctx(tmp_path)
    data = pipeline.load(ctx)
    data["predictions"] = pd.DataFrame({"image_id": [data["images"]["image_id"].iloc[0]], "class_id": [7],
                                        "x": [10.0], "y": [10.0], "w": [20.0], "h": [20.0], "conf": [0.9]})
    with pytest.raises(LabelMapError):
        pipeline.process(ctx, data)


# ---------------------------------------------------------------- failure cases (load / provenance)
def _copy_fixture(tmp_path):
    dst = tmp_path / "fx"
    shutil.copytree(FX, dst)
    return dst


def test_load_rejects_tampered_input(tmp_path):
    fx = _copy_fixture(tmp_path)
    with open(fx / "model_predictions_fixture.csv", "a", encoding="utf-8") as f:
        f.write("aa_00,2,1,1,5,5,0.99\n")                             # hash no longer matches manifest.csv
    with pytest.raises(ValueError, match="provenance"):
        pipeline.load(_ctx(tmp_path / "out", input_dir=fx, strict_provenance=True))


def test_load_fails_clearly_when_required_file_is_missing(tmp_path):
    fx = _copy_fixture(tmp_path)
    (fx / "taxonomy.yaml").unlink()
    with pytest.raises(FileNotFoundError, match="taxonomy.yaml"):
        pipeline.load(_ctx(tmp_path / "out", input_dir=fx, strict_provenance=False))
