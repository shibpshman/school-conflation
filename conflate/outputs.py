"""Write the deliverables for one state into results/<STATE>/."""

import geopandas as gpd
from shapely.geometry import LineString, box

CLASS_ORDER = ["matched", "ambiguous", "missing"]


def write(data, res, out_dir, insets):
    out_dir.mkdir(parents=True, exist_ok=True)
    nces, osm = data.nces.to_crs("EPSG:4326"), data.osm.to_crs("EPSG:4326")
    cols = ["ncessch", "name", "street", "city", "zip", "county", "metro_area", "locale",
            "locale_group", "lat", "lon"]
    table = nces[cols].merge(res, on="ncessch", how="left")
    table = table.rename(columns={"class": "match_class"})
    table["name_score"] = table.name_score.round(3)
    table["score"] = table.score.round(3)
    table["distance_m"] = table.distance_m.round(0)

    # matches.csv / matches.gpkg: one row per NCES school
    table.to_csv(out_dir / "matches.csv", index=False)
    gpkg = out_dir / "matches.gpkg"
    gpkg.unlink(missing_ok=True)
    gpd.GeoDataFrame(table, geometry=nces.geometry.values, crs=nces.crs).to_file(
        gpkg, layer="nces_schools")

    # OSM schools with their role, outlines kept
    used = set(res.loc[res["class"].isin(["matched", "ambiguous"]), "osm_key"])
    o = osm[["osm_key", "name", "operator", "operator_type", "isced_level", "addr_city",
             "duplicate_of", "name_from", "geometry"]].copy()
    o["role"] = "osm_only"
    o.loc[o.osm_key.isin(used), "role"] = "matched_or_ambiguous"
    o.loc[o.duplicate_of != "", "role"] = "duplicate"
    o.to_file(gpkg, layer="osm_schools")
    pts = o.copy()
    pts["geometry"] = pts.geometry.representative_point()
    pts.to_file(gpkg, layer="osm_points")

    # lines from each NCES point to its OSM match, for the maps
    by_key = dict(zip(pts.osm_key, pts.geometry))
    linked = table[table.osm_key.fillna("") != ""]
    lines = gpd.GeoDataFrame(
        linked[["ncessch", "match_class", "osm_key"]],
        geometry=[LineString([(r.lon, r.lat), by_key[r.osm_key].coords[0]])
                  for r in linked.itertuples()], crs="EPSG:4326")
    lines.to_file(gpkg, layer="match_links")

    # osm_only.csv: unmatched OSM schools, then duplicates
    only = pts[pts.role.isin(["osm_only", "duplicate"])].copy()
    only["lat"], only["lon"] = only.geometry.y.round(6), only.geometry.x.round(6)
    only = only.sort_values(["role", "name"], ascending=[False, True])
    only.drop(columns="geometry").to_csv(out_dir / "osm_only.csv", index=False)

    # review_queue.csv: ambiguous cases, most likely matches first (quick confirmations)
    queue = table[table.match_class == "ambiguous"].sort_values("score", ascending=False)
    queue.insert(0, "priority", range(1, len(queue) + 1))
    queue.to_csv(out_dir / "review_queue.csv", index=False)

    # map context, not a deliverable
    ctx = out_dir / "context.gpkg"
    ctx.unlink(missing_ok=True)
    state = data.counties.dissolve()[["geometry"]]
    data.counties.to_file(ctx, layer="counties")
    state.to_file(ctx, layer="state")
    gpd.clip(data.roads, state).to_file(ctx, layer="roads")
    insets.to_file(ctx, layer="insets")

    counts = table.match_class.value_counts().reindex(CLASS_ORDER, fill_value=0)
    roles = o.role.value_counts()
    return {"nces_schools": len(table), **counts.to_dict(),
            "osm_schools": len(o), "osm_only": int(roles.get("osm_only", 0)),
            "osm_duplicates": int(roles.get("duplicate", 0))}


def pick_insets(data, res):
    """Two insets chosen from the data, in EPSG:4326.

    metro: the metro area (NCES CBSA) with the most city-locale schools, framed on those
    schools and widened to at least 4:5 so the inset is not a sliver. rural: the county with the most schools left unmatched among counties with at
    least 15 schools, two thirds of them in rural locales.
    """
    t = data.nces.to_crs("EPSG:4326").merge(res[["ncessch", "class"]])
    rows = []
    core = t[(t.locale_group == "city") & (t.metro_area != "")]
    if len(core):
        name = core.metro_area.value_counts().idxmax()
        pts = core[core.metro_area == name].to_crs(data.nces.crs)  # meters
        x0, y0, x1, y1 = pts.total_bounds
        pad = 0.08 * max(x1 - x0, y1 - y0)
        x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        grow = max(0.0, 0.8 * (y1 - y0) - (x1 - x0)) / 2
        frame = gpd.GeoSeries([box(x0 - grow, y0, x1 + grow, y1)], crs=data.nces.crs)
        frame = frame.to_crs("EPSG:4326").iloc[0]
        inside = t[t.within(frame)]
        rows.append({"inset": "metro", "name": f"{name} metro", "geometry": frame,
                     "schools": len(inside),
                     "matched_share": round(float((inside["class"] == "matched").mean()), 3)})
    g = t.groupby("county").agg(n=("ncessch", "size"),
                                rural=("locale_group", lambda s: (s == "rural").mean()),
                                unmatched=("class", lambda s: int((s != "matched").sum())),
                                matched=("class", lambda s: (s == "matched").mean()))
    rural = g[(g.n >= 15) & (g.rural >= 2 / 3)].sort_values("unmatched", ascending=False)
    if len(rural):
        name = rural.index[0]
        geom = data.counties.set_index("name").geometry[name]
        rows.append({"inset": "rural", "name": name, "geometry": geom,
                     "schools": int(rural.n.iloc[0]),
                     "matched_share": round(float(rural.matched.iloc[0]), 3)})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
