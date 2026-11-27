"""Extract schools and map context from a Geofabrik .osm.pbf extract with pyosmium.

Schools are every object tagged amenity=school: nodes, closed ways and multipolygon relations.
Ways and relations keep their full outline. Roads (motorway to secondary) come along for the maps.
"""

import osmium
import osmium.filter
import osmium.geom
import geopandas as gpd
from shapely import wkb

SCHOOL_TAGS = ["name", "alt_name", "official_name", "short_name", "old_name", "operator",
               "operator:type", "isced:level", "school", "addr:city", "addr:street",
               "addr:housenumber"]
ROAD_CLASSES = ("motorway", "trunk", "primary", "secondary")


def _osm_type(obj):
    if isinstance(obj, osmium.osm.Area):
        return "way" if obj.from_way() else "relation"
    return {"n": "node", "w": "way", "r": "relation"}[obj.type_str()]


def extract(pbf_path):
    """Return (schools, roads) as GeoDataFrames in EPSG:4326."""
    wkbf = osmium.geom.WKBFactory()
    schools, roads = [], []
    open_school_ways = 0

    fp = (osmium.FileProcessor(str(pbf_path))
          .with_areas(osmium.filter.TagFilter(("amenity", "school")))
          .with_filter(osmium.filter.TagFilter(("amenity", "school"),
                                               *[("highway", c) for c in ROAD_CLASSES])))
    for obj in fp:
        tags = obj.tags
        if tags.get("amenity") == "school":
            if obj.is_node():
                geom = wkb.loads(wkbf.create_point(obj), hex=True)
            elif obj.is_area():
                try:
                    geom = wkb.loads(wkbf.create_multipolygon(obj), hex=True)
                except RuntimeError:  # broken multipolygon in the source data
                    continue
            elif obj.is_way():
                # Closed ways arrive again as areas; count only the open ones here.
                if not obj.is_closed():
                    open_school_ways += 1
                continue
            else:  # relations arrive as areas
                continue
            schools.append({"osm_type": _osm_type(obj),
                            "osm_id": obj.orig_id() if obj.is_area() else obj.id,
                            **{k.replace(":", "_"): tags.get(k, "") for k in SCHOOL_TAGS},
                            "geometry": geom})
        elif obj.is_way() and tags.get("highway") in ROAD_CLASSES:
            try:
                geom = wkb.loads(wkbf.create_linestring(obj), hex=True)
            except RuntimeError:
                continue
            roads.append({"highway": tags["highway"], "ref": tags.get("ref", ""),
                          "geometry": geom})

    crs = "EPSG:4326"
    schools = gpd.GeoDataFrame(schools, geometry="geometry", crs=crs)
    schools["osm_key"] = schools.osm_type + "/" + schools.osm_id.astype(str)
    roads = gpd.GeoDataFrame(roads, geometry="geometry", crs=crs)
    schools.attrs["open_school_ways"] = open_school_ways
    return schools, roads


if __name__ == "__main__":
    import sys
    s, r = extract(sys.argv[1])
    print(len(s), s.osm_type.value_counts().to_dict(), "open ways:", s.attrs["open_school_ways"])
    print((s.name == "").sum(), "unnamed;", len(r), "road ways")
