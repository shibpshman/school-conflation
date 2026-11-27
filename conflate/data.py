"""Load and prepare everything one state's run needs."""

from dataclasses import dataclass

import geopandas as gpd

from . import inputs, osm, sources
from .match import prepare_osm, project


@dataclass
class StateData:
    state: str
    state_name: str
    nces: gpd.GeoDataFrame      # projected (UTM), one point per NCES school
    osm: gpd.GeoDataFrame       # projected, OSM schools as mapped (points or outlines)
    counties: gpd.GeoDataFrame  # EPSG:4326
    roads: gpd.GeoDataFrame     # EPSG:4326
    osm_file: str


def load(state, osm_date=sources.OSM_DATE):
    state = state.upper()
    nces_zip, county_zip = sources.get(sources.NCES_URL), sources.get(sources.COUNTY_URL)
    counties, state_name = inputs.load_counties(county_zip, state)
    osm_url = sources.geofabrik_url(state_name, osm_date)
    pbf = sources.get(osm_url, osm_url + ".md5")
    nces = inputs.load_nces(nces_zip, state)
    schools, roads = osm.extract(pbf)
    nces, schools = project(nces, schools)
    return StateData(state, state_name, nces, prepare_osm(schools), counties, roads, pbf.name)
