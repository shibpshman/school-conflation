import math

import pandas as pd
import pytest

from conflate.metrics import score_rows, summarize, wilson
from conflate.truth import allocate, resolve


def frame(rows, cols):
    return pd.DataFrame(rows, columns=cols)


PRED = frame([("a", "matched", "way/1"),     # right object: TP
              ("b", "matched", "way/2"),     # wrong object: FP and FN
              ("c", "matched", "way/3"),     # not in OSM: FP
              ("d", "missing", ""),          # in OSM, missed: FN
              ("e", "missing", ""),          # not in OSM, missing: correct negative
              ("f", "ambiguous", "way/6"),   # right object in review: FN, review hit
              ("g", "matched", "node/7")],   # one of two accepted keys: TP
             ["ncessch", "class", "osm_key"])
TRUTH = frame([("a", "test", "way/1"), ("b", "test", "way/9"), ("c", "test", "none"),
               ("d", "test", "way/4"), ("e", "test", "none"), ("f", "test", "way/6"),
               ("g", "test", "way/7;node/7"), ("h", "test", "skip")],
              ["ncessch", "split", "truth"])


def test_counts():
    s = summarize(score_rows(PRED, TRUTH))
    assert s["schools"] == 7  # the skip row is dropped
    assert (s["tp"], s["fp"], s["fn"]) == (2, 2, 3)
    assert s["in_osm"] == 5
    assert s["precision"] == pytest.approx(2 / 4)
    assert s["recall"] == pytest.approx(2 / 5)
    assert s["f1"] == pytest.approx(2 * 0.5 * 0.4 / 0.9)
    assert s["review_recall"] == pytest.approx(3 / 5)
    assert s["ambiguous"] == 1


def test_no_predictions_gives_nan_precision():
    pred = PRED.assign(**{"class": "missing", "osm_key": ""})
    s = summarize(score_rows(pred, TRUTH))
    assert math.isnan(s["precision"]) and s["recall"] == 0 and s["f1"] == 0


def test_wilson():
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert all(math.isnan(x) for x in wilson(0, 0))


def test_resolve_answers():
    keys = ["way/1", "node/2", None]
    assert resolve(1, keys) == "way/1"
    assert resolve(2.0, keys) == "node/2"
    assert resolve(" None ", keys) == "none"
    assert resolve("skip", keys) == "skip"
    assert resolve(None, keys) == ""
    assert resolve("way/120", keys) == "way/120"
    assert resolve("1; relation/5", keys) == "way/1;relation/5"
    with pytest.raises(ValueError):
        resolve(3, keys)
    with pytest.raises(ValueError):
        resolve("maybe", keys)


def test_allocate_is_proportional_and_exact():
    sizes = pd.Series({"city": 241, "suburb": 89, "town": 216, "rural": 381})
    out = allocate(sizes, 150)
    assert out.sum() == 150
    assert (abs(out - sizes / sizes.sum() * 150) < 1).all()


def test_read_sheet_keeps_blanks_as_none(tmp_path):
    from openpyxl import Workbook
    from conflate.truth import read_sheet
    wb = Workbook()
    ws = wb.active
    ws.title = "label"
    ws.append(["label_id", "answer", "notes", "key_1", "key_2"])
    ws.append([1, None, None, "way/1", None])
    ws.append([2, 1, "x", "way/2", None])
    wb.save(tmp_path / "s.xlsx")
    df = read_sheet(tmp_path / "s.xlsx")
    assert df.answer.tolist() == [None, 1] and df.key_2.tolist() == [None, None]


def test_import_accepts_same_named_objects_and_outlines(tmp_path, monkeypatch):
    from openpyxl import Workbook
    from conflate import truth
    keys = [f"key_{k}" for k in range(1, truth.MAX_CANDIDATES + 1)]
    wb = Workbook()
    ws = wb.active
    ws.title = "label"
    ws.append(["label_id", "ncessch", "split", "answer", "notes"] + keys)
    pad = [None] * (truth.MAX_CANDIDATES - 3)
    ws.append([1, "a", "test", 1, None, "way/1", "node/2", "node/3"] + pad)  # outline chosen
    ws.append([2, "b", "test", 3, None, "way/1", "node/2", "node/3"] + pad)  # dup node chosen
    ws.append([3, "c", "tune", "none", None, "way/1", "node/2", "node/3"] + pad)
    wb.save(tmp_path / "labeling_sheet.xlsx")
    osm = pd.DataFrame({"osm_key": ["way/1", "node/2", "node/3"],
                        "name": ["Tatum High School", "Tatum High", "Tatum Junior High School"],
                        "duplicate_of": ["", "", "way/1"]})
    monkeypatch.setattr(truth, "truth_dir", lambda state: tmp_path)
    assert truth.import_sheet("NM", osm) == []
    t = pd.read_csv(tmp_path / "truth.csv", dtype=str, keep_default_na=False)
    got = dict(zip(t.label_id, t.truth))
    assert set(got["1"].split(";")) == {"way/1", "node/2"}  # junior high is not the same school
    assert set(got["2"].split(";")) == {"node/3", "way/1", "node/2"}  # via its outline
    assert got["3"] == "none"
