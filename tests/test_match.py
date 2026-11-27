import geopandas as gpd
from shapely.geometry import Point, box

from conflate.match import OSM_NAME_FIELDS, Params, prepare_osm, run

CRS = "EPSG:26913"  # NAD83 / UTM 13N, meters


def nces(*rows):
    return gpd.GeoDataFrame(
        {"ncessch": [r[0] for r in rows], "name": [r[1] for r in rows]},
        geometry=[Point(r[2], r[3]) for r in rows], crs=CRS)


def osm(*rows):
    """rows: (key, name, geometry)"""
    df = gpd.GeoDataFrame({"osm_key": [r[0] for r in rows]},
                          geometry=[r[2] for r in rows], crs=CRS)
    for f in OSM_NAME_FIELDS:
        df[f] = ""
    df["name"] = [r[1] for r in rows]
    return prepare_osm(df)


def classes(res):
    return dict(zip(res.ncessch, res["class"])), dict(zip(res.ncessch, res.osm_key))


def test_exact_name_inside_outline_matches():
    n = nces(("1", "WILSON MIDDLE", 50, 50))
    o = osm(("way/1", "Wilson Middle School", box(0, 0, 100, 100)))
    res, _ = run(n, o, Params(radius_m=1000, threshold=0.75))
    cls, key = classes(res)
    assert cls["1"] == "matched" and key["1"] == "way/1"
    assert res.distance_m.iloc[0] == 0
    assert "Wilson Middle School" in res.reason.iloc[0]


def test_far_away_is_missing():
    n = nces(("1", "WILSON MIDDLE", 0, 0))
    o = osm(("node/1", "Wilson Middle School", Point(5000, 0)))
    res, _ = run(n, o, Params(radius_m=1000, threshold=0.75))
    assert res["class"].iloc[0] == "missing"
    assert "no OSM school within 1000 m" in res.reason.iloc[0]


def test_one_to_one_second_school_goes_ambiguous():
    n = nces(("1", "ELIDA HIGH", 50, 50), ("2", "ELIDA ELEMENTARY", 60, 60))
    o = osm(("way/1", "Elida High School", box(0, 0, 100, 100)))
    res, _ = run(n, o, Params(radius_m=1000, threshold=0.75))
    cls, key = classes(res)
    assert cls["1"] == "matched" and key["1"] == "way/1"
    assert cls["2"] in ("ambiguous", "missing")
    assert key["2"] in ("", "way/1")


def test_unnamed_school_is_never_matched():
    n = nces(("1", "CAPITAN MIDDLE", 50, 50))
    o = osm(("way/1", "", box(0, 0, 100, 100)))
    res, _ = run(n, o, Params(radius_m=1000, threshold=0.6))
    assert res["class"].iloc[0] == "ambiguous"
    assert "no name" in res.reason.iloc[0]


def test_close_runner_up_makes_ambiguous():
    n = nces(("1", "LINCOLN ELEMENTARY", 0, 0))
    o = osm(("node/1", "Lincoln Elementary School", Point(10, 0)),
            ("node/2", "Lincoln Elementary", Point(-12, 0)))
    res, _ = run(n, o, Params(radius_m=1000, threshold=0.75))
    assert res["class"].iloc[0] == "ambiguous"
    assert "runner-up" in res.reason.iloc[0]


def test_duplicate_node_inside_same_named_outline():
    o = osm(("way/1", "Taylor Elementary School", box(0, 0, 100, 100)),
            ("node/1", "Taylor Elementary", Point(50, 50)))
    dup = dict(zip(o.osm_key, o.duplicate_of))
    assert dup == {"way/1": "", "node/1": "way/1"}


def test_unnamed_outline_takes_name_of_node_inside():
    o = osm(("way/1", "", box(0, 0, 100, 100)),
            ("node/1", "Park Junior High School", Point(50, 50)))
    row = o.set_index("osm_key").loc["way/1"]
    assert row["name"] == "Park Junior High School" and row["name_from"] == "node/1"
    assert o.set_index("osm_key").loc["node/1", "duplicate_of"] == "way/1"


def test_two_named_schools_in_one_unnamed_campus_both_stay():
    o = osm(("way/1", "", box(0, 0, 200, 200)),
            ("node/1", "Cimarron Elementary", Point(50, 50)),
            ("node/2", "Cimarron High School", Point(150, 150)))
    dup = dict(zip(o.osm_key, o.duplicate_of))
    assert dup["node/1"] == "" and dup["node/2"] == ""
