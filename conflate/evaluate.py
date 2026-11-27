"""Score the run against the held-out half of the truth set, for both methods."""

import json

from . import metrics, splink_bench
from .names import normalize
from .truth import load_truth, truth_dir


def report(data, res, pairs, params, out_dir, splink=True):
    truth = load_truth(data.state)
    pfile = truth_dir(data.state) / "params.json"
    if truth is None or not pfile.exists():
        print("no truth set and tuned params for this state yet: skipping evaluation")
        return None
    test = truth[truth.split == "test"]
    rows = metrics.score_rows(res, test)
    ours = metrics.summarize(rows)
    lines = [f"# Evaluation, {data.state}", "",
             f"Held-out half of the truth set: {len(test)} schools "
             f"({int((test.truth == 'skip').sum())} skipped as unjudgeable). "
             f"Blocking radius {params.radius_m:.0f} m, match threshold {params.threshold:.2f}, "
             f"both set on the tune half.", "",
             "## Hand-built matcher", "",
             metrics.table({"all": ours, **metrics.by_group(rows, data.nces)}), ""]
    result = {"ours": ours}

    if splink:
        st = json.loads(pfile.read_text())["splink_threshold"]
        nces = data.nces.copy()
        nces["norm_name"] = nces.name.map(normalize)
        scored = splink_bench.score(nces, data.osm, pairs)
        sres = splink_bench.classify(nces, data.osm, scored, st)
        srows = metrics.score_rows(sres, test)
        theirs = metrics.summarize(srows)
        result["splink"] = theirs
        lines += [f"## Splink (same blocked pairs, threshold {st:.2f} on match probability)", "",
                  metrics.table({"all": theirs, **metrics.by_group(srows, data.nces)}), ""]
        both = rows[["ncessch", "tp"]].merge(srows[["ncessch", "tp"]], on="ncessch",
                                              suffixes=("_ours", "_splink"))
        lines += [f"Correct by the hand-built matcher only: "
                  f"{int((both.tp_ours & ~both.tp_splink).sum())}; by Splink only: "
                  f"{int((~both.tp_ours & both.tp_splink).sum())}.", ""]
        sres.to_csv(out_dir / "splink_matches.csv", index=False)

    # the misses, so the README can say what goes wrong
    misses = rows[rows.fp | rows.fn].merge(res[["ncessch", "reason"]], on="ncessch")
    misses = misses.merge(data.nces[["ncessch", "name"]], on="ncessch").rename(
        columns={"class": "cls"})
    lines += ["## Errors on the held-out half", "",
              "| school | class | truth | matcher picked | reason |", "|---|---|---|---|---|"]
    for r in misses.itertuples():
        lines.append(f"| {r.name} | {r.cls} | {r.truth} | {r.osm_key or '-'} | {r.reason} |")
    (out_dir / "evaluation.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    clean = lambda s: {k: (list(v) if isinstance(v, tuple) else v) for k, v in s.items()}
    return {k: clean(v) for k, v in result.items()}
