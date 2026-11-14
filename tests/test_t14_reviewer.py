"""Tests for src/t14_reviewer.py (Member 3 — Human-in-the-Loop & Decision Gate). No ground truth needed."""
import json
from pathlib import Path

import pandas as pd
import pytest

from src import main as runner
from src import t14_reviewer as rv

REVIEW_COLS = ["reviewer", "reviewer_decision", "override_value", "review_note", "reviewed_at"]


def _run(out):
    return runner.main(["--track", "t14", "--config", "configs/lab.yaml", "--output", str(out), "--offline", "--seed", "42"])


def _write_review(out, decide_row):
    """Fill the reviewer columns of out/review_queue.csv using decide_row(row) -> (decision, override) or None."""
    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    for i, r in q.iterrows():
        d = decide_row(r)
        if d:
            q.loc[i, REVIEW_COLS] = ["tester", d[0], d[1], "unit test", "2026-11-14T10:00:00Z"]
    q.to_csv(out / rv.REVIEWED_FILE, index=False)
    return q


def _decision(out):
    return json.loads((out / "decision.json").read_text(encoding="utf-8"))


def test_no_review_file_means_hold(tmp_path):
    assert _run(tmp_path) == 0
    d = _decision(tmp_path)
    assert d["status"] == "HOLD" and d["reason_code"] == "REVIEW_INCOMPLETE" and d["owner"]


def test_full_review_applies_decisions_audits_and_goes(tmp_path):
    assert _run(tmp_path) == 0
    before = pd.read_csv(tmp_path / "predictions.csv")
    q = pd.read_csv(tmp_path / "review_queue.csv")
    dropped = q[q["slice"].str.endswith("/dropped")]["item_id"].tolist()
    kept = q[q["slice"].str.endswith("/kept")]["item_id"].tolist()
    restore, reject, edit = dropped[0], kept[0], kept[1]
    new_class = "sign" if before.set_index("box_id").at[edit, "class"] != "sign" else "car"

    def rule(r):
        if r["item_id"] == reject:
            return "reject", "drop"
        if r["item_id"] == edit:
            return "edit", f"class={new_class}"
        # approve the one below-threshold box we restore and every kept box; reject the other dropped ones
        return ("approve", "") if r["item_id"] == restore or r["item_id"] in kept else ("reject", "drop")

    _write_review(tmp_path, rule)
    assert _run(tmp_path) == 0
    after = pd.read_csv(tmp_path / "predictions.csv").set_index("box_id")
    assert restore in after.index and restore not in set(before["box_id"])      # approve restores
    assert reject not in after.index                                             # reject drops
    assert after.at[edit, "class"] == new_class                                  # edit overrides the class
    assert len(after) == len(before)                                             # +1 restored, -1 rejected

    d = _decision(tmp_path)
    assert d["status"] == "GO" and d["metrics"]["queue_reviewed"] == d["metrics"]["queue_size"] == 30
    audit = [json.loads(ln) for ln in (tmp_path / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()]
    reviews = [a for a in audit if a["action"].startswith("review:")]
    assert len(reviews) == 30 and all(a["actor"] == "tester" for a in reviews)


def test_partial_review_stays_on_hold(tmp_path):
    assert _run(tmp_path) == 0
    first = pd.read_csv(tmp_path / "review_queue.csv")["item_id"].iloc[0]
    _write_review(tmp_path, lambda r: ("approve", "") if r["item_id"] == first else None)
    assert _run(tmp_path) == 0
    d = _decision(tmp_path)
    assert d["status"] == "HOLD" and d["metrics"]["queue_reviewed"] == 1


def test_bad_override_fails_loudly():
    names = {"car", "pedestrian", "motorbike", "sign"}
    assert rv.parse_override("class=motorbike; x=10", names) == {"class": "motorbike", "x": 10.0}
    with pytest.raises(ValueError):
        rv.parse_override("class=truck", names)          # not in the taxonomy
    with pytest.raises(ValueError):
        rv.parse_override("make it bigger", names)
