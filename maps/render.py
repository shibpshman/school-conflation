"""Build the QGIS project for one state's results and export its three maps.

Runs under a Python that can import qgis (system QGIS 3.44 LTR), headless:

    QT_QPA_PLATFORM=offscreen /usr/bin/python3 maps/render.py results/NM "New Mexico"

It writes results/<STATE>/school_conflation.qgz (layers, styles and three print layouts, with
paths relative to the project), then opens that project and exports each layout to PNG, so the
committed project and the images cannot drift apart.
"""

import json
import sys
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsApplication, QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsFillSymbol, QgsLayout, QgsLayoutExporter, QgsLayoutItemLabel,
    QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemScaleBar, QgsLayoutMeasurement,
    QgsLayoutPoint, QgsLayoutSize, QgsLegendStyle, QgsLineSymbol, QgsMarkerSymbol,
    QgsPalLayerSettings, QgsPrintLayout, QgsProject, QgsRectangle, QgsRendererCategory,
    QgsRuleBasedRenderer, QgsTextFormat, QgsUnitTypes, QgsVectorLayer,
    QgsVectorLayerSimpleLabeling, QgsLayerTreeLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

# Colors: the first three slots of a validated categorical palette (all pairs pass CVD checks),
# each class also gets its own shape, so color never carries the meaning alone.
SURFACE, PLANE = "#fcfcfb", "#f2f1ec"
INK, INK2, MUTED, HAIR = "#0b0b0b", "#52514e", "#898781", "#d6d5ce"
CLASSES = [  # value, label, color, shape, size mm (drawn bottom to top)
    ("matched", "Matched to an OSM school", "#2a78d6", "circle", 1.9),
    ("ambiguous", "Ambiguous, needs a human look", "#1baf7a", "diamond", 2.6),
    ("missing", "Missing from OSM", "#eb6834", "triangle", 2.8),
]
FONT = "Noto Sans"
DPI = 200


def text_format(size, color=INK, bold=False):
    f = QgsTextFormat()
    font = QFont(FONT)
    font.setBold(bold)
    f.setFont(font)
    f.setSize(size)
    f.setColor(QColor(color))
    return f


def vlayer(gpkg, layer, name, subset=""):
    opts = QgsVectorLayer.LayerOptions()
    opts.forceReadOnly = True  # read-only: no SQLite write locks between layers of one file
    lyr = QgsVectorLayer(f"{gpkg}|layername={layer}", name, "ogr", opts)
    if not lyr.isValid():
        raise SystemExit(f"cannot open {gpkg} layer {layer}")
    if subset:
        lyr.setSubsetString(subset)
    return lyr


def build(out, state_name, project):
    ctx, gpkg = str(out / "context.gpkg"), str(out / "matches.gpkg")
    summary = json.loads((out / "summary.json").read_text())

    state = vlayer(ctx, "state", "State")
    state.setRenderer(state.renderer().__class__(QgsFillSymbol.createSimple(
        {"color": SURFACE, "outline_color": INK2, "outline_width": "0.35"})))

    counties = vlayer(ctx, "counties", "Counties")
    counties.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"style": "no", "outline_color": HAIR, "outline_width": "0.2"}))

    roads = vlayer(ctx, "roads", "Major roads", "highway IN ('motorway','trunk','primary')")
    roads.renderer().setSymbol(QgsLineSymbol.createSimple(
        {"line_color": "#c9c8c1", "line_width": "0.3"}))
    minor = vlayer(ctx, "roads", "Secondary roads", "highway = 'secondary'")
    minor.renderer().setSymbol(QgsLineSymbol.createSimple(
        {"line_color": "#dddcd5", "line_width": "0.2"}))

    insets = vlayer(ctx, "insets", "Inset areas")
    insets.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"style": "no", "outline_color": INK, "outline_width": "0.5"}))
    lab = QgsPalLayerSettings()
    lab.fieldName = "name"
    lab.setFormat(text_format(7, INK, bold=True))
    lab.placement = Qgis.LabelPlacement.OutsidePolygons
    insets.setLabeling(QgsVectorLayerSimpleLabeling(lab))
    insets.setLabelsEnabled(True)

    outlines = vlayer(gpkg, "osm_schools", "OSM school outlines",
                      "ST_GeometryType(geom) LIKE '%POLYGON%'")
    outlines.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "#e6e5df", "outline_color": "#b5b4ac", "outline_width": "0.15"}))

    links = vlayer(gpkg, "match_links", "Match links")
    links.renderer().setSymbol(QgsLineSymbol.createSimple(
        {"line_color": INK2, "line_width": "0.2"}))

    only = vlayer(gpkg, "osm_points", "OSM only", "role = 'osm_only'")
    only.renderer().setSymbol(QgsMarkerSymbol.createSimple(
        {"name": "square", "color": "255,255,255,0", "outline_color": MUTED,
         "outline_width": "0.3", "size": "1.5"}))
    only.setName("OSM school with no NCES match")

    nces = vlayer(gpkg, "nces_schools", "NCES public schools")
    cats = []
    for value, label, color, shape, size in CLASSES:
        sym = QgsMarkerSymbol.createSimple({"name": shape, "color": color, "size": str(size),
                                            "outline_color": SURFACE, "outline_width": "0.25"})
        cats.append(QgsRendererCategory(value, sym, label))
    renderer = QgsCategorizedSymbolRenderer("match_class", cats)
    nces.setRenderer(renderer)
    # missing on top, matched at the bottom
    order = renderer.orderBy()
    from qgis.core import QgsFeatureRequest
    nces.renderer().setOrderBy(QgsFeatureRequest.OrderBy([QgsFeatureRequest.OrderByClause(
        "CASE match_class WHEN 'missing' THEN 3 WHEN 'ambiguous' THEN 2 ELSE 1 END", True)]))
    nces.renderer().setOrderByEnabled(True)

    # missing-school names, shown only in the rural inset
    named = vlayer(gpkg, "nces_schools", "Missing school names", "match_class = 'missing'")
    named.renderer().setSymbol(QgsMarkerSymbol.createSimple({"size": "0", "color": "0,0,0,0",
                                                              "outline_style": "no"}))
    nl = QgsPalLayerSettings()
    nl.fieldName = "name"
    fmt = text_format(5.5, INK2)
    buf = fmt.buffer()
    buf.setEnabled(True)
    buf.setSize(0.6)
    buf.setColor(QColor(SURFACE))
    fmt.setBuffer(buf)
    nl.setFormat(fmt)
    nl.placement = Qgis.LabelPlacement.AroundPoint
    nl.dist = 1.2
    named.setLabeling(QgsVectorLayerSimpleLabeling(nl))
    named.setLabelsEnabled(True)

    for lyr in [state, counties, minor, roads, outlines, links, insets, only, nces, named]:
        project.addMapLayer(lyr)
    root = project.layerTreeRoot()
    # layer tree order = draw order, top first
    for i, lyr in enumerate([named, nces, only, insets, links, outlines, roads, minor, counties,
                             state]):
        node = root.findLayer(lyr.id())
        clone = node.clone()
        root.insertChildNode(i, clone)
        node.parent().removeChildNode(node)

    lon0 = state.extent().center().x()
    zone = int((lon0 + 180) // 6) + 1
    crs = QgsCoordinateReferenceSystem(f"EPSG:{26900 + zone}")  # NAD83 / UTM, north
    project.setCrs(crs)
    to_map = QgsCoordinateTransform(state.crs(), crs, project)

    def extent_of(layer, expr=None, pad=0.04):
        if expr:
            from qgis.core import QgsFeatureRequest
            feats = layer.getFeatures(QgsFeatureRequest().setFilterExpression(expr))
            r = QgsRectangle()
            r.setNull()
            for f in feats:
                r.combineExtentWith(f.geometry().boundingBox())
        else:
            r = layer.extent()
        r = to_map.transformBoundingBox(r)
        r.grow(max(r.width(), r.height()) * pad)
        return r

    inset_rows = {f["inset"]: f for f in insets.getFeatures()}
    nm = summary["nces_schools"]
    subtitle = (f"{nm} public schools in the NCES 2024-25 list, matched to "
                f"OpenStreetMap schools by name and distance: {summary['matched']} matched, "
                f"{summary['ambiguous']} ambiguous, {summary['missing']} missing from OSM.")
    maps = [("statewide", f"{state_name} public schools in OpenStreetMap", subtitle,
             extent_of(state), [nces, only, insets, roads, counties, state]),]
    if "metro" in inset_rows:
        f = inset_rows["metro"]
        maps.append(("metro", f"{f['name']}: the largest school system",
                     f"{f['schools']} NCES schools in this frame, {f['matched_share']:.0%} "
                     f"matched. Gray shapes are OSM school grounds; lines join each NCES point "
                     f"to the OSM object it matched.",
                     extent_of(insets, "\"inset\" = 'metro'", 0.0),
                     [nces, only, links, outlines, roads, minor, counties, state]))
    if "rural" in inset_rows:
        f = inset_rows["rural"]
        maps.append(("rural", f"{f['name']}: the largest rural gap",
                     f"Of the mostly rural counties, the one with the most schools not matched: "
                     f"{f['schools']} NCES schools, {f['matched_share']:.0%} matched. Missing "
                     f"schools are named.", extent_of(insets, "\"inset\" = 'rural'", 0.04),
                     [named, nces, only, links, outlines, roads, minor, counties, state]))

    attribution = ("Schools: NCES EDGE Public School Geocodes 2024-25 (public domain). "
                   "OSM schools and roads: © OpenStreetMap contributors, ODbL, Geofabrik "
                   f"extract {summary['osm_extract'].rsplit('-', 1)[1][:6]}. Counties: US Census "
                   "Bureau cartographic boundaries 2024.")
    manager = project.layoutManager()
    for key, title, sub, extent, layers in maps:
        manager.addLayout(make_layout(project, key, title, sub, extent, layers, attribution,
                                      legend_layers=[nces, only]))


def make_layout(project, key, title, sub, extent, layers, attribution, legend_layers):
    W, M = 220.0, 8.0  # page width mm, margin
    map_w = W - 2 * M
    map_h = map_w * extent.height() / extent.width()
    H = M + 22 + map_h + 40  # final height is set once the legend is placed
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(key)
    page = layout.pageCollection().page(0)
    page.setPageSize(QgsLayoutSize(W, H, QgsUnitTypes.LayoutMillimeters))
    page.setPageStyleSymbol(QgsFillSymbol.createSimple({"color": PLANE, "style": "solid",
                                                        "outline_style": "no"}))

    def label(text, y, size, color=INK, bold=False, h=8):
        it = QgsLayoutItemLabel(layout)
        it.setText(text)
        it.setTextFormat(text_format(size, color, bold))
        it.setMode(QgsLayoutItemLabel.ModeFont)
        it.attemptMove(QgsLayoutPoint(M, y, QgsUnitTypes.LayoutMillimeters))
        it.attemptResize(QgsLayoutSize(map_w, h, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(it)
        return it

    label(title, M, 15, INK, bold=True, h=8)
    label(sub, M + 8.5, 8.5, INK2, h=12)

    mp = QgsLayoutItemMap(layout)
    mp.attemptMove(QgsLayoutPoint(M, M + 22, QgsUnitTypes.LayoutMillimeters))
    mp.attemptResize(QgsLayoutSize(map_w, map_h, QgsUnitTypes.LayoutMillimeters))
    mp.setCrs(project.crs())
    mp.setLayers(layers)
    mp.setKeepLayerSet(True)
    mp.setExtent(extent)
    mp.setBackgroundColor(QColor(PLANE))
    mp.setFrameEnabled(True)
    mp.setFrameStrokeColor(QColor(HAIR))
    layout.addLayoutItem(mp)

    y = M + 22 + map_h + 3
    lg = QgsLayoutItemLegend(layout)
    lg.setLinkedMap(mp)
    lg.setAutoUpdateModel(False)
    model_root = lg.model().rootGroup()
    model_root.removeAllChildren()
    for lyr in legend_layers:
        model_root.addLayer(lyr)
    lg.setTitle("")
    for style in (QgsLegendStyle.Subgroup, QgsLegendStyle.SymbolLabel):
        lg.rstyle(style).setTextFormat(text_format(8, INK))
    lg.setLegendFilterByMapEnabled(False)
    lg.setBackgroundEnabled(False)
    lg.setColumnCount(2)
    lg.setSplitLayer(True)
    lg.setEqualColumnWidth(True)
    lg.setSymbolHeight(3.2)
    lg.attemptMove(QgsLayoutPoint(M - 1, y, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(lg)
    # the layer name for NCES is a group heading; hide it, the categories say enough
    from qgis.core import QgsLegendRenderer
    for node in model_root.findLayers():
        if node.layer().name().startswith("NCES"):
            QgsLegendRenderer.setNodeLegendStyle(node, QgsLegendStyle.Hidden)
    lg.refresh()

    sb = QgsLayoutItemScaleBar(layout)
    sb.setStyle("Line Ticks Up")
    sb.setLinkedMap(mp)
    sb.setUnits(QgsUnitTypes.DistanceKilometers)
    sb.setUnitLabel("km")
    sb.setNumberOfSegments(2)
    sb.setNumberOfSegmentsLeft(0)
    mm_per_km = map_w / (extent.width() / 1000)
    km = max([v for v in (1, 2, 4, 10, 20, 40, 100, 200) if v * mm_per_km <= 40] or [1])
    sb.setUnitsPerSegment(km / 2)
    sb.setTextFormat(text_format(7, INK2))

    sb.setHeight(1.5)
    sb.attemptMove(QgsLayoutPoint(W - M - km * mm_per_km - 10, y + 2,
                                  QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(sb)

    y_attr = y + 18  # two legend rows; the legend reports no size until it is drawn
    label(attribution, y_attr, 6.5, MUTED, h=8)
    page.setPageSize(QgsLayoutSize(W, y_attr + 8 + M / 2, QgsUnitTypes.LayoutMillimeters))
    return layout


def export(project_path, out):
    project = QgsProject.instance()
    project.clear()
    if not project.read(str(project_path)):
        raise SystemExit(f"cannot read {project_path}")
    for layout in project.layoutManager().printLayouts():
        # renderPageToImage + QImage.save: a plain PNG, no GDAL georeferencing pass
        image = QgsLayoutExporter(layout).renderPageToImage(0, dpi=DPI)
        png = out / f"map_{layout.name()}.png"
        if image.isNull() or not image.save(str(png)):
            raise SystemExit(f"export of {layout.name()} failed")
        print("wrote", png)


def main():
    out, state_name = Path(sys.argv[1]).resolve(), sys.argv[2]
    app = QgsApplication([], False)
    app.initQgis()
    project = QgsProject.instance()
    project.setFilePathStorage(Qgis_relative())
    build(out, state_name, project)
    qgz = out / "school_conflation.qgz"
    if not project.write(str(qgz)):
        raise SystemExit(f"cannot write {qgz}")
    relativize(qgz, out)
    export(qgz, out)
    app.exitQgis()


def relativize(qgz, out):
    """Layouts store absolute layer paths as a fallback; make them relative like the rest."""
    import zipfile
    with zipfile.ZipFile(qgz) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    for n in parts:
        if n.endswith(".qgs"):
            parts[n] = parts[n].replace(f'source="{out}/'.encode(), b'source="./')
    with zipfile.ZipFile(qgz, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in parts.items():
            z.writestr(n, data)


def Qgis_relative():
    from qgis.core import Qgis
    return Qgis.FilePathType.Relative


if __name__ == "__main__":
    main()
