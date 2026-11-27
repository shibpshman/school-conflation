"""The hand-labeled truth set: sampling, the labeling sheet, and importing the answers.

    python -m conflate.truth sample --state NM   # draw the sample, write the labeling sheet
    python -m conflate.truth import --state NM   # read the filled sheet into truth.csv

The sample is stratified by NCES locale group (city, suburb, town, rural) in proportion to the
state's own mix, so the unweighted precision and recall estimate the whole state. Each stratum
is split in half before any tuning: "tune" rows may set the threshold and the blocking radius,
"test" rows are only ever used for the reported numbers.

The sheet lists OSM candidates nearest first, without the matcher's scores, so the labels are not
steered by the method they will grade.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .names import normalize
from .sources import ROOT

SAMPLE_SIZE = 150
SEED = 20261126
CANDIDATE_RADIUS_M = 3000
MAX_CANDIDATES = 6
HIDDEN = ["ncessch", "split"] + [f"key_{k}" for k in range(1, MAX_CANDIDATES + 1)]

INSTRUCTIONS = """\
School conflation truth set: how to label

Each row is one public school from the NCES list. Decide which OpenStreetMap object, if any, is that
school, and type it in the "answer" column. Work from the links: "OSM map" opens openstreetmap.org
at the school's NCES location, "Satellite" opens aerial imagery there, and each candidate link opens
that OSM object. Check the school's own website or a search when the name or the spot is unclear.

What to type in "answer":
  1 to 6      the numbered candidate is this school
  way/123     an OSM object that is not in the candidate list (copy its type and number from the
              openstreetmap.org address bar: node/..., way/... or relation/...)
  none        the school exists at a real site, but no OSM school object represents it
  skip        cannot be judged: an online-only school, a closed school, or no way to tell

Rules:
- A match means the OSM object stands for this school's site (its building or its grounds), even
  if the OSM name differs, for example an old name or a district name.
- Several schools on one campus: if OSM has one object for the whole campus, enter that object for
  each school on it. Write "shared campus" in notes.
- If OSM has both a point and an outline for the school, enter either one, or both separated by
  a semicolon (way/123;node/456).
- An object only counts if it is tagged as a school in OSM. A building with the school's name but
  no school tag, or a prison with a school inside it, is "none".
- The OSM data is the 1 January 2026 extract. If openstreetmap.org shows an object that is not in
  the candidate list and looks new, still enter it: the import step will say so if it is not in
  the extract.
- Use notes for anything a reviewer should know: unsure, renamed, wrong NCES location, and so on.

Columns to the right of the candidates are used by the import step. Leave them alone.
When done, save the file in place (keep .xlsx) and run: python -m conflate.truth import --state NM
"""


def truth_dir(state):
    return ROOT / "truth" / state


def allocate(sizes, n):
    """Largest-remainder proportional allocation of n across strata."""
    raw = sizes / sizes.sum() * n
    out = np.floor(raw).astype(int)
    out[(raw - out).sort_values(ascending=False).index[: n - out.sum()]] += 1
    return out


def draw_sample(nces, n=SAMPLE_SIZE, seed=SEED):
    """Stratified sample with a tune/test split inside each stratum."""
    rng = np.random.default_rng(seed)
    sizes = nces.groupby("locale_group").size()
    parts = []
    for group, k in allocate(sizes, n).items():
        pool = nces[nces.locale_group == group].sort_values("ncessch")
        pick = pool.iloc[rng.permutation(len(pool))[:k]].copy()
        pick["split"] = ["tune" if i < k // 2 else "test" for i in range(k)]
        parts.append(pick)
    sample = pd.concat(parts)
    sample = sample.iloc[rng.permutation(len(sample))]  # mix strata so labeling order is random
    sample.insert(0, "label_id", range(1, len(sample) + 1))
    return sample


def candidates(school_geom, osm):
    d = osm.geometry.distance(school_geom)
    near = d[d <= CANDIDATE_RADIUS_M].sort_values()
    if len(near) == 0:
        near = d.sort_values().head(2)
    return [(osm.at[i, "osm_key"], osm.at[i, "name"], osm.at[i, "duplicate_of"], dist)
            for i, dist in near.head(MAX_CANDIDATES).items()]


def osm_url(key):
    return f"https://www.openstreetmap.org/{key}"


def write_sheet(sample, osm, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "label"
    visible = ["label_id", "school", "address", "locale", "answer", "notes", "OSM map",
               "Satellite"] + [f"candidate {k}" for k in range(1, MAX_CANDIDATES + 1)]
    ws.append(visible + HIDDEN)
    link = Font(color="0563C1", underline="single")
    for r, row in enumerate(sample.itertuples(), start=2):
        cands = candidates(row.geometry, osm)
        ws.append([row.label_id, row.name, f"{row.street}, {row.city}  ({row.county})",
                   row.locale_group, None, None, None, None]
                  + [None] * MAX_CANDIDATES
                  + [row.ncessch, row.split] + [c[0] for c in cands]
                  + [None] * (MAX_CANDIDATES - len(cands)))
        lat, lon = row.lat, row.lon
        links = [(7, f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=18/{lat}/{lon}",
                  "OSM map"),
                 (8, f"https://www.google.com/maps/@?api=1&map_action=map&center={lat},{lon}"
                     f"&zoom=18&basemap=satellite", "Satellite")]
        for k, (key, name, dup, dist) in enumerate(cands, start=1):
            label = f"{k}) {name or '(no name)'} · {key} · {dist:,.0f} m"
            if dup:
                label += f" · duplicate of {dup}"
            links.append((8 + k, osm_url(key), label))
        for col, url, text in links:
            cell = ws.cell(row=r, column=col, value=text)
            cell.hyperlink = url
            cell.font = link
    n = len(sample) + 1
    dv = DataValidation(type="list", formula1='"1,2,3,4,5,6,none,skip"', allow_blank=True,
                        showErrorMessage=False)
    ws.add_data_validation(dv)
    dv.add(f"E2:E{n}")
    widths = [8, 38, 46, 8, 12, 30, 10, 10] + [44] * MAX_CANDIDATES
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    for i in range(len(visible) + 1, len(visible) + len(HIDDEN) + 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].hidden = True
    fill = PatternFill("solid", fgColor="FFF2CC")
    for r in range(1, n + 1):
        for c in (5, 6):
            ws.cell(row=r, column=c).fill = fill
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.freeze_panes = "C2"
    help_ws = wb.create_sheet("how to label", 0)
    for line in INSTRUCTIONS.splitlines():
        help_ws.append([line])
    help_ws.column_dimensions["A"].width = 110
    help_ws["A1"].font = Font(bold=True, size=13)
    for row in help_ws.iter_rows():
        row[0].alignment = Alignment(wrap_text=False)
    wb.active = 1
    wb.save(path)


def read_sheet(path):
    ws = load_workbook(path)["label"]
    rows = list(ws.iter_rows(values_only=True))
    df = pd.DataFrame(rows[1:], columns=rows[0]).astype(object)
    return df.where(df.notna(), None)  # blank cells stay None, not NaN


def resolve(answer, keys):
    """Turn one answer cell into 'none', 'skip', '' (blank) or a ;-joined list of OSM keys."""
    if isinstance(answer, float) and answer.is_integer():
        answer = int(answer)
    a = "" if answer is None else str(answer).strip().lower()
    if a in ("", "none", "skip"):
        return a
    out = []
    for part in a.replace(",", ";").split(";"):
        part = part.strip()
        if part.isdigit():
            k = int(part)
            if not (1 <= k <= len(keys)) or not keys[k - 1]:
                raise ValueError(f"candidate {k} does not exist")
            out.append(keys[k - 1])
        elif part.split("/")[0] in ("node", "way", "relation") and part.split("/")[-1].isdigit():
            out.append(part)
        else:
            raise ValueError(f"cannot read {part!r}")
    return ";".join(out)


def import_sheet(state, osm):
    d = truth_dir(state)
    df = read_sheet(d / "labeling_sheet.xlsx")
    key_cols = [f"key_{k}" for k in range(1, MAX_CANDIDATES + 1)]
    known = set(osm.osm_key)
    canonical = dict(zip(osm.osm_key, osm.duplicate_of))
    norm = {k: n for k, n in zip(osm.osm_key, osm.name.map(normalize)) if n}
    out, problems = [], []
    for row in df.itertuples(index=False):
        r = row._asdict()
        try:
            truth = resolve(r["answer"], [r[c] for c in key_cols])
        except ValueError as e:
            problems.append(f"label {r['label_id']}: {e}")
            continue
        if truth not in ("", "none", "skip"):
            keys = truth.split(";")
            missing = [k for k in keys if k not in known]
            if missing:
                problems.append(f"label {r['label_id']}: {', '.join(missing)} not in the extract")
                continue
            # A duplicate node stands for its outline too, which is what the matcher sees.
            keys += [canonical[k] for k in keys if canonical.get(k)]
            # The sheet says an outline and a point for one school are both right: accept any
            # candidate whose normalized name is identical to a chosen object's.
            chosen = {norm[k] for k in keys if norm.get(k)}
            keys += [k for k in (r[c] for c in key_cols) if k and norm.get(k) in chosen]
            truth = ";".join(dict.fromkeys(keys))
        out.append({"label_id": r["label_id"], "ncessch": r["ncessch"], "split": r["split"],
                    "truth": truth, "notes": r["notes"] or ""})
    t = pd.DataFrame(out)
    blank = (t.truth == "").sum()
    t[t.truth != ""].to_csv(d / "truth.csv", index=False)
    print(f"{len(t) - blank} labeled, {blank} blank, {len(problems)} problems -> {d / 'truth.csv'}")
    for p in problems:
        print("  ", p)
    return problems


def load_truth(state):
    p = truth_dir(state) / "truth.csv"
    return pd.read_csv(p, dtype=str, keep_default_na=False) if p.exists() else None


def main():
    from .data import load
    ap = argparse.ArgumentParser(prog="python -m conflate.truth")
    ap.add_argument("command", choices=["sample", "import"])
    ap.add_argument("--state", default="NM")
    ap.add_argument("--force", action="store_true", help="overwrite an existing labeling sheet")
    a = ap.parse_args()
    data = load(a.state)
    d = truth_dir(data.state)
    if a.command == "sample":
        sheet = d / "labeling_sheet.xlsx"
        if sheet.exists() and not a.force:
            raise SystemExit(f"{sheet} exists and may hold labels; use --force to replace it")
        d.mkdir(parents=True, exist_ok=True)
        sample = draw_sample(data.nces)
        sample[["label_id", "ncessch", "name", "locale_group", "split"]].to_csv(
            d / "sample.csv", index=False)
        write_sheet(sample, data.osm, sheet)
        print(f"{len(sample)} schools -> {sheet}")
        print(sample.groupby(["locale_group", "split"]).size().unstack().to_string())
    else:
        if import_sheet(data.state, data.osm):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
