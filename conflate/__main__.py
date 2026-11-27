"""python -m conflate --state NM [--no-maps]

Downloads the pinned sources, matches NCES public schools to OpenStreetMap schools, writes the
tables to results/<STATE>/, evaluates against the held-out truth set when one exists, runs the
Splink benchmark, and renders the maps with PyQGIS.
"""

import argparse
import json
import os
import subprocess
import sys

from . import evaluate, outputs, sources
from .data import load
from .match import run
from .tune import load_params


def main():
    ap = argparse.ArgumentParser(prog="python -m conflate")
    ap.add_argument("--state", default="NM", help="two-letter state code (default NM)")
    ap.add_argument("--osm-date", default=sources.OSM_DATE,
                    help="Geofabrik extract date, YYMMDD (default %(default)s)")
    ap.add_argument("--no-maps", action="store_true", help="skip the PyQGIS map step")
    ap.add_argument("--no-splink", action="store_true", help="skip the Splink benchmark")
    ap.add_argument("--qgis-python", default=os.environ.get("QGIS_PYTHON", "/usr/bin/python3"),
                    help="a Python that can import qgis (default $QGIS_PYTHON or "
                         "/usr/bin/python3)")
    a = ap.parse_args()

    data = load(a.state, a.osm_date)
    params = load_params(data.state)
    res, pairs = run(data.nces, data.osm, params)
    out = sources.ROOT / "results" / data.state
    insets = outputs.pick_insets(data, res)
    summary = {"state": data.state, "osm_extract": data.osm_file,
               "nces_file": sources.NCES_URL.rsplit("/", 1)[1],
               "params": vars(params), **outputs.write(data, res, out, insets)}
    print(json.dumps(summary, indent=2))

    report = evaluate.report(data, res, pairs, params, out, splink=not a.no_splink)
    if report:
        summary["evaluation"] = report
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    if not a.no_maps:
        script = sources.ROOT / "maps" / "render.py"
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([a.qgis_python, str(script), str(out), data.state_name], env=env)
        if r.returncode:
            sys.exit("map step failed; the tables are written. Rerun with --no-maps to skip it.")


if __name__ == "__main__":
    main()
