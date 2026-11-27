"""Read the NCES school list and the Census county outlines for one state."""

import zipfile

import geopandas as gpd
import pandas as pd

# The pipe-delimited TXT in the NCES zip has no header row; these are the xlsx's column names.
NCES_COLUMNS = ("NCESSCH LEAID NAME OPSTFIPS STREET CITY STATE ZIP STFIP CNTY NMCNTY LOCALE LAT LON "
                "CBSA NMCBSA CBSATYPE CSA NMCSA CD SLDL SLDU SCHOOLYEAR").split()
LOCALE_GROUPS = {"1": "city", "2": "suburb", "3": "town", "4": "rural"}


def load_nces(zip_path, state):
    with zipfile.ZipFile(zip_path) as z:
        txt = next(n for n in z.namelist() if n.upper().endswith(".TXT"))
        df = pd.read_csv(z.open(txt), sep="|", dtype=str, header=None, names=NCES_COLUMNS,
                         keep_default_na=False, encoding="utf-8")
    df = df[df.STATE == state].copy()
    if df.empty:
        raise SystemExit(f"No NCES schools for state {state!r}")
    df["locale_group"] = df.LOCALE.str[0].map(LOCALE_GROUPS)
    df["NMCBSA"] = df.NMCBSA.replace("N", "")  # NCES writes N for "not in a metro area"
    df = df[["NCESSCH", "NAME", "STREET", "CITY", "ZIP", "NMCNTY", "NMCBSA", "LOCALE",
             "locale_group", "LAT", "LON"]].rename(columns={
        "NCESSCH": "ncessch", "NAME": "name", "STREET": "street", "CITY": "city", "ZIP": "zip",
        "NMCNTY": "county", "NMCBSA": "metro_area", "LOCALE": "locale", "LAT": "lat",
        "LON": "lon"})
    df["lat"], df["lon"] = df.lat.astype(float), df.lon.astype(float)
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")


def load_counties(zip_path, state):
    """Counties of the state (EPSG:4326) and the state's full name."""
    g = gpd.read_file(f"zip://{zip_path}")
    g = g[g.STUSPS == state].to_crs("EPSG:4326")
    if g.empty:
        raise SystemExit(f"Unknown state code {state!r}")
    return g[["GEOID", "NAMELSAD", "geometry"]].rename(columns={"NAMELSAD": "name"}), \
        g.STATE_NAME.iloc[0]
