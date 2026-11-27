"""Benchmark: Splink (Fellegi-Sunter, DuckDB backend) scoring the same blocked pairs.

Splink gets the exact candidate pairs the hand-built matcher sees (registered with
register_blocked_pairs_for_predict), the same normalized names, and two comparisons: Jaro-Winkler
name similarity and distance in km. u probabilities come from random sampling, m probabilities
from expectation maximisation, with no labels. The match probability then goes through the same
greedy one-to-one assignment, with its threshold set on the same tune half.
"""

import logging

import numpy as np
import pandas as pd
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

SEP = "-__-"


def _inputs(nces, osm):
    n = nces.to_crs("EPSG:4326")
    left = pd.DataFrame({"source_dataset": "nces", "unique_id": n.ncessch.values,
                         "name_norm": n.norm_name.values, "lat": n.geometry.y.values,
                         "lon": n.geometry.x.values})
    live = osm[osm.duplicate_of == ""]
    pts = live.geometry.representative_point().to_crs("EPSG:4326")
    right = pd.DataFrame({"source_dataset": "osm", "unique_id": live.osm_key.values,
                          "name_norm": live.norm_name.replace("", None).values,
                          "lat": pts.y.values, "lon": pts.x.values})
    for df in (left, right):
        df["lat_r"], df["lon_r"] = df.lat.round(2), df.lon.round(2)  # ~1 km cells for EM
    return left, right, live


def score(nces, osm, pairs):
    """Return pairs (nces_idx, osm_idx) with a Splink match_probability column."""
    logging.getLogger("splink").setLevel(logging.WARNING)
    left, right, live = _inputs(nces, osm)
    db = DuckDBAPI()
    settings = SettingsCreator(
        link_type="link_only",
        comparisons=[cl.JaroWinklerAtThresholds("name_norm", [0.95, 0.88, 0.75]),
                     cl.DistanceInKMAtThresholds("lat", "lon", [0.05, 0.2, 0.5, 1.5])],
        retain_intermediate_calculation_columns=False,
    )
    linker = Linker([db.register(left, table_name="nces"), db.register(right, table_name="osm")],
                    settings, log_level=logging.WARNING)
    t = linker.training
    t.estimate_probability_two_random_records_match([block_on("name_norm")], recall=0.7)
    t.estimate_u_using_random_sampling(max_pairs=2e6, seed=1)
    t.estimate_parameters_using_expectation_maximisation(block_on("lat_r", "lon_r"))
    t.estimate_parameters_using_expectation_maximisation(block_on("name_norm"))

    ids = pd.DataFrame({
        "match_key": "0",
        "join_key_l": "nces" + SEP + nces.ncessch.loc[pairs.nces_idx].values,
        "join_key_r": "osm" + SEP + live.osm_key.loc[pairs.osm_idx].values})
    linker.table_management.register_blocked_pairs_for_predict(
        db.register(ids, table_name="blocked_pairs"))
    pred = linker.inference.predict().as_pandas_dataframe()
    pred = pred[["unique_id_l", "unique_id_r", "match_probability"]]
    out = pairs[["nces_idx", "osm_idx", "distance_m", "name_score"]].copy()
    out["unique_id_l"] = nces.ncessch.loc[out.nces_idx].values
    out["unique_id_r"] = live.osm_key.loc[out.osm_idx].values
    out = out.merge(pred, on=["unique_id_l", "unique_id_r"], how="left")
    assert out.match_probability.notna().all(), "Splink skipped some blocked pairs"
    out["score"] = out.match_probability
    return out.drop(columns=["unique_id_l", "unique_id_r"])


def classify(nces, osm, scored, threshold):
    """Greedy one-to-one on match probability; matched or missing (Splink has no review band)."""
    taken_n, taken_o, rows = set(), set(), {}
    for r in scored[scored.score >= threshold].sort_values("score", ascending=False).itertuples():
        if r.nces_idx in taken_n or r.osm_idx in taken_o:
            continue
        taken_n.add(r.nces_idx)
        taken_o.add(r.osm_idx)
        rows[r.nces_idx] = (osm.at[r.osm_idx, "osm_key"], r.score)
    return pd.DataFrame({"ncessch": nces.ncessch.values,
                         "class": ["matched" if i in rows else "missing" for i in nces.index],
                         "osm_key": [rows.get(i, ("", 0))[0] for i in nces.index],
                         "score": [rows.get(i, ("", np.nan))[1] for i in nces.index]})
