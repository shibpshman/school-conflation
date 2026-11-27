"""Hand-built matcher: name similarity plus distance, one-to-one assignment, three classes.

score = NAME_WEIGHT * name_similarity + (1 - NAME_WEIGHT) * exp(-distance / DIST_SCALE_M)

Distance is from the NCES point to the OSM object, which is 0 when the point falls inside a
school's mapped outline. Two values are tuned on the labeled tune half (see tune.py): the
blocking radius and the match threshold. The rest are fixed by design, so a 75-school tuning set
is not asked to fit six knobs.
"""

import math
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd

from .names import normalize, similarity

NAME_WEIGHT = 0.7
DIST_SCALE_M = 300.0
AMBIGUOUS_BAND = 0.15     # scores this far below the threshold go to review, not to "missing"
RUNNER_UP_MARGIN = 0.05   # a second candidate this close makes a match ambiguous
UNNAMED_NAME_SCORE = 0.5  # an unnamed OSM school is neither evidence for nor against
DUPLICATE_RADIUS_M = 100.0
OSM_NAME_FIELDS = ["name", "official_name", "alt_name", "short_name", "old_name"]


@dataclass
class Params:
    radius_m: float = 1500.0
    threshold: float = 0.75


def project(nces, osm):
    crs = nces.estimate_utm_crs()
    return nces.to_crs(crs), osm.to_crs(crs)


def prepare_osm(osm):
    """Normalize OSM names and flag duplicates.

    A smaller object (a node, or a building outline) is a duplicate of a larger school outline
    within DUPLICATE_RADIUS_M when their names match (similarity >= 0.9), or when one of the two
    is unnamed and the smaller lies inside the outline. An unnamed outline then takes the name of
    the named object inside it (name_from says which). Duplicates are kept for the report but
    never matched.
    """
    osm = osm.copy()
    for f in OSM_NAME_FIELDS:
        osm[f"norm_{f}"] = osm[f].map(normalize)
    osm["area_m2"] = osm.geometry.area
    osm["duplicate_of"] = ""
    polys = osm[osm.area_m2 > 0]
    pairs = gpd.sjoin(osm[["geometry"]], polys[["geometry"]], predicate="dwithin",
                      distance=DUPLICATE_RADIUS_M)
    pairs = pairs[pairs.index != pairs.index_right]
    best = {}
    for i, j in zip(pairs.index, pairs.index_right):
        if osm.at[j, "area_m2"] <= osm.at[i, "area_m2"]:
            continue
        ni, nj = osm.at[i, "norm_name"], osm.at[j, "norm_name"]
        same = ni and nj and similarity(ni, nj) >= 0.9
        one_unnamed = (not ni or not nj) and osm.geometry[j].contains(osm.geometry[i])
        if (same or one_unnamed) and osm.at[j, "area_m2"] > best.get(i, (0, None))[0]:
            best[i] = (osm.at[j, "area_m2"], j)
    # Several differently named schools inside one unnamed outline (a shared campus) all stay.
    named_in = {}
    for i, (_, j) in best.items():
        if osm.at[i, "norm_name"] and not osm.at[j, "norm_name"]:
            named_in.setdefault(j, set()).add(osm.at[i, "norm_name"])
    best = {i: v for i, v in best.items()
            if not (osm.at[i, "norm_name"] and len(named_in.get(v[1], ())) > 1)}
    osm["name_from"] = ""
    for i, (_, j) in best.items():
        while j in best:  # node -> building -> campus resolves to the campus
            j = best[j][1]
        ni, nj = osm.at[i, "norm_name"], osm.at[j, "norm_name"]
        if ni and nj and similarity(ni, nj) < 0.9:
            continue  # reached a campus with another school's name: i is its own school
        osm.at[i, "duplicate_of"] = osm.at[j, "osm_key"]
    # Name an unnamed outline after the named objects inside it, when they agree on one name.
    named_dups = osm[(osm.duplicate_of != "") & (osm.norm_name != "")]
    for key, g in named_dups.groupby("duplicate_of"):
        j = osm.index[osm.osm_key == key][0]
        if not osm.at[j, "norm_name"]:
            for f in OSM_NAME_FIELDS:
                osm.at[j, f], osm.at[j, f"norm_{f}"] = g[f].iloc[0], g[f"norm_{f}"].iloc[0]
            osm.at[j, "name_from"] = g.osm_key.iloc[0]
    return osm


def candidate_pairs(nces, osm, radius_m):
    """Every (NCES school, OSM school) pair within radius_m, with name and distance scores."""
    live = osm[osm.duplicate_of == ""]
    pairs = gpd.sjoin(nces[["geometry"]], live[["geometry"]], predicate="dwithin",
                      distance=radius_m)
    i, j = pairs.index.to_numpy(), pairs.index_right.to_numpy()
    dist = nces.geometry.loc[i].distance(live.geometry.loc[j], align=False).to_numpy()
    rows = []
    for a, b, d in zip(i, j, dist):
        norm = nces.at[a, "norm_name"]
        named = [(similarity(norm, live.at[b, f"norm_{f}"]), f) for f in OSM_NAME_FIELDS
                 if live.at[b, f"norm_{f}"]]
        if named:
            name_score, field = max(named)
        else:
            name_score, field = UNNAMED_NAME_SCORE, ""
        rows.append((a, b, name_score, field, d))
    out = pd.DataFrame(rows, columns=["nces_idx", "osm_idx", "name_score", "name_field",
                                      "distance_m"])
    out["dist_score"] = np.exp(-out.distance_m / DIST_SCALE_M)
    out["score"] = NAME_WEIGHT * out.name_score + (1 - NAME_WEIGHT) * out.dist_score
    out["unnamed"] = out.name_field == ""
    return out


def assign(pairs, threshold):
    """Greedy one-to-one assignment: best remaining pair first, nothing below the review floor."""
    floor = threshold - AMBIGUOUS_BAND
    taken_n, taken_o, chosen = set(), set(), []
    for row in pairs[pairs.score >= floor].sort_values("score", ascending=False).itertuples():
        if row.nces_idx in taken_n or row.osm_idx in taken_o:
            continue
        taken_n.add(row.nces_idx)
        taken_o.add(row.osm_idx)
        chosen.append(row.Index)
    return pairs.loc[chosen]


def _osm_label(osm, j):
    name = osm.at[j, "name"]
    return f"{osm.at[j, 'osm_key']} '{name}'" if name else f"{osm.at[j, 'osm_key']} (unnamed)"


def classify(nces, osm, pairs, params):
    """One row per NCES school: class, OSM match, scores and a one-line reason."""
    t, floor = params.threshold, params.threshold - AMBIGUOUS_BAND
    chosen = assign(pairs, t).set_index("nces_idx")
    owner = dict(zip(chosen.osm_idx, chosen.index))
    by_school = {k: g.sort_values("score", ascending=False) for k, g in pairs.groupby("nces_idx")}
    rows = []
    for idx in nces.index:
        cands = by_school.get(idx)
        rec = {"ncessch": nces.at[idx, "ncessch"], "class": "missing", "osm_key": "",
               "osm_name": "", "name_score": np.nan, "distance_m": np.nan, "score": np.nan}
        if idx in chosen.index:
            c = chosen.loc[idx]
            j = c.osm_idx
            rec.update(osm_key=osm.at[j, "osm_key"], osm_name=osm.at[j, "name"],
                       name_score=c.name_score, distance_m=c.distance_m, score=c.score)
            others = cands[cands.osm_idx != j]
            runner = others.iloc[0] if len(others) else None
            what = (f"name {c.name_score:.2f} vs {c.name_field} '{osm.at[j, c.name_field]}'"
                    if c.name_field else "OSM school has no name")
            if c.name_field and osm.at[j, "name_from"]:
                what += f" (from {osm.at[j, 'name_from']} inside the outline)"
            base = f"{what}, {c.distance_m:.0f} m, score {c.score:.2f}"
            if c.unnamed:
                rec["class"], reason = "ambiguous", base
            elif c.score < t:
                rec["class"], reason = "ambiguous", f"{base}, below the {t:.2f} match threshold"
            elif runner is not None and c.score - runner.score < RUNNER_UP_MARGIN:
                rec["class"] = "ambiguous"
                reason = (f"{base}; runner-up {_osm_label(osm, runner.osm_idx)} "
                          f"scored {runner.score:.2f}")
            else:
                rec["class"], reason = "matched", base
        elif cands is None:
            reason = f"no OSM school within {params.radius_m:.0f} m"
        else:
            top = cands.iloc[0]
            j = top.osm_idx
            if top.score >= floor and j in owner:
                rec["class"] = "ambiguous"
                other = nces.loc[owner[j]]
                reason = (f"best candidate {_osm_label(osm, j)} ({top.distance_m:.0f} m, score "
                          f"{top.score:.2f}) went to {other['name']} ({other.ncessch}); "
                          f"shared campus?")
                rec.update(osm_key=osm.at[j, "osm_key"], osm_name=osm.at[j, "name"],
                           name_score=top.name_score, distance_m=top.distance_m, score=top.score)
            else:
                reason = (f"best candidate {_osm_label(osm, j)} at {top.distance_m:.0f} m "
                          f"scored {top.score:.2f}, below the {floor:.2f} review floor")
        rec["reason"] = reason
        rows.append(rec)
    return pd.DataFrame(rows)


def run(nces, osm, params):
    """nces, osm: projected GeoDataFrames (osm already through prepare_osm)."""
    nces = nces.copy()
    nces["norm_name"] = nces.name.map(normalize)
    pairs = candidate_pairs(nces, osm, params.radius_m)
    return classify(nces, osm, pairs, params), pairs
