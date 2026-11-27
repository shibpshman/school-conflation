"""Set the blocking radius and the match threshold on the tune half of the truth set.

    python -m conflate.tune --state NM

Grid search, best F1 on tune rows only; ties go to higher precision, then the smaller radius.
The held-out half is never read here. The chosen values land in truth/<STATE>/params.json,
which every later run uses. A state with no truth set of its own uses New Mexico's values.
The Splink threshold is tuned the same way, on the same rows.
"""

import argparse
import json

import numpy as np

from . import metrics, splink_bench
from .match import Params, candidate_pairs, classify
from .names import normalize
from .truth import load_truth, truth_dir

RADII = [500, 1000, 1500, 2000, 3000]
THRESHOLDS = np.round(np.arange(0.50, 0.96, 0.01), 2)
SPLINK_THRESHOLDS = np.round(np.r_[0.005, 0.01, 0.02, 0.03, np.arange(0.05, 1.0, 0.05)], 3)


def load_params(state):
    for s in (state, "NM"):
        p = truth_dir(s) / "params.json"
        if p.exists():
            j = json.loads(p.read_text())
            return Params(j["radius_m"], j["threshold"])
    return Params()


def _key(s, radius):
    return (s["f1"], s["precision"] if s["precision"] == s["precision"] else 0, -radius)


def tune(data, truth):
    tune_rows = truth[truth.split == "tune"]
    nces = data.nces.copy()
    nces["norm_name"] = nces.name.map(normalize)
    best, grid = None, []
    for radius in RADII:
        pairs = candidate_pairs(nces, data.osm, radius)
        for t in THRESHOLDS:
            res = classify(nces, data.osm, pairs, Params(radius, float(t)))
            s = metrics.summarize(metrics.score_rows(res, tune_rows))
            grid.append({"radius_m": radius, "threshold": float(t), "f1": s["f1"],
                         "precision": s["precision"], "recall": s["recall"]})
            if best is None or _key(s, radius) > _key(best[1], best[0].radius_m):
                best = (Params(radius, float(t)), s)
    params, s = best

    # Splink on the same blocked pairs as the chosen radius
    pairs = candidate_pairs(nces, data.osm, params.radius_m)
    scored = splink_bench.score(nces, data.osm, pairs)
    sbest = None
    for t in SPLINK_THRESHOLDS:
        ss = metrics.summarize(metrics.score_rows(
            splink_bench.classify(nces, data.osm, scored, t), tune_rows))
        if sbest is None or _key(ss, 0) > _key(sbest[1], 0):
            sbest = (float(t), ss)
    return params, s, sbest, grid


def main():
    from .data import load
    ap = argparse.ArgumentParser(prog="python -m conflate.tune")
    ap.add_argument("--state", default="NM")
    a = ap.parse_args()
    data = load(a.state)
    truth = load_truth(data.state)
    if truth is None:
        raise SystemExit("No truth.csv yet: label the sheet, then python -m conflate.truth import")
    params, s, (st, ss), grid = tune(data, truth)
    out = {"radius_m": params.radius_m, "threshold": params.threshold,
           "splink_threshold": st,
           "tune_rows": int((truth.split == "tune").sum()),
           "tune_f1": round(s["f1"], 4), "tune_precision": round(s["precision"], 4),
           "tune_recall": round(s["recall"], 4), "splink_tune_f1": round(ss["f1"], 4)}
    d = truth_dir(data.state)
    (d / "params.json").write_text(json.dumps(out, indent=2) + "\n")
    (d / "tune_grid.json").write_text(json.dumps(grid) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
