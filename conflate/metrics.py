"""Precision and recall against the hand-labeled truth set.

A school counts as a true positive only when it is classed "matched" AND the OSM object is one
the labeler accepted. A match to the wrong object is both a false positive and a false negative.
"Review recall" also credits a correct object sitting in the ambiguous class, which is what the
pipeline delivers once a person clears the review queue.
"""

import math

import pandas as pd


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes in n trials."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def score_rows(pred, truth):
    """Join predictions to labels; drop 'skip' rows. One row per labeled school."""
    t = truth[truth.truth != "skip"][["ncessch", "split", "truth"]]
    df = t.merge(pred[["ncessch", "class", "osm_key"]], on="ncessch", how="left")
    df["osm_key"] = df.osm_key.fillna("")
    keys = df.truth.map(lambda s: set() if s == "none" else set(s.split(";")))
    hit = pd.Series([k in ks for k, ks in zip(df.osm_key, keys)], index=df.index)
    df["in_osm"] = keys.map(bool)
    df["tp"] = (df["class"] == "matched") & hit
    df["fp"] = (df["class"] == "matched") & ~df.tp
    df["fn"] = df.in_osm & ~df.tp
    df["review_hit"] = df["class"].isin(["matched", "ambiguous"]) & hit
    return df


def summarize(df):
    tp, fp, fn = int(df.tp.sum()), int(df.fp.sum()), int(df.fn.sum())
    in_osm = int(df.in_osm.sum())
    p = tp / (tp + fp) if tp + fp else math.nan
    r = tp / (tp + fn) if tp + fn else math.nan
    f1 = 2 * p * r / (p + r) if tp else 0.0
    return {"schools": len(df), "in_osm": in_osm, "tp": tp, "fp": fp, "fn": fn,
            "precision": p, "precision_ci": wilson(tp, tp + fp),
            "recall": r, "recall_ci": wilson(tp, tp + fn), "f1": f1,
            "ambiguous": int((df["class"] == "ambiguous").sum()),
            "review_recall": int(df.review_hit.sum()) / in_osm if in_osm else math.nan}


def by_group(df, nces, col="locale_group"):
    g = df.merge(nces[["ncessch", col]], on="ncessch")
    return {k: summarize(v) for k, v in g.groupby(col)}


def fmt(x):
    return "n/a" if x != x else f"{x:.2f}"


def table(rows):
    """Markdown table from {label: summarize(...)}."""
    out = ["| | schools | in OSM | precision (95% CI) | recall (95% CI) | F1 | ambiguous "
           "| recall after review |", "|---|---|---|---|---|---|---|---|"]
    for label, s in rows.items():
        pci, rci = s["precision_ci"], s["recall_ci"]
        out.append(f"| {label} | {s['schools']} | {s['in_osm']} | {fmt(s['precision'])} "
                   f"({fmt(pci[0])}-{fmt(pci[1])}) | {fmt(s['recall'])} "
                   f"({fmt(rci[0])}-{fmt(rci[1])}) | {fmt(s['f1'])} | {s['ambiguous']} "
                   f"| {fmt(s['review_recall'])} |")
    return "\n".join(out)
