#!/usr/bin/env python3

import html
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


INPUT_FILE = Path("atak/data/ladot-speed-safety.geojson")
OUTPUT_FILE = Path("atak/data/kml/ladot-speed-safety.kml")

KML_NS = "http://www.opengis.net/kml/2.2"

ET.register_namespace("", KML_NS)


def kml_tag(name):
    return f"{{{KML_NS}}}{name}"


def add_text(parent, name, value):
    element = ET.SubElement(parent, kml_tag(name))
    element.text = str(value)
    return element


def make_description(properties):
    street = properties.get("StreetName", "")
    from_street = properties.get("XStreet2", "")
    to_street = properties.get("XStreet1", "")
    district = properties.get("DISTRICT", "")
    speed_limit = properties.get("speed_limi", "")
    equity = properties.get("EquityArea", "")
    school = properties.get("SchoolNearby", "")
    collisions = properties.get("SpeedCollisions2", "")
    percent_speeding = properties.get("Percentspeed", "")
    vehicles = properties.get("TotalVehicles", "")

    rows = [
        ("Street", street),
        ("From", from_street),
        ("To", to_street),
        ("Council District", district),
        ("Speed Limit", f"{speed_limit} mph" if speed_limit != "" else ""),
        ("Equity Area", equity),
        ("School Nearby", school),
        ("Speed-Related Collisions", collisions),
        ("Percent Speeding", percent_speeding),
        ("Total Vehicles", vehicles),
    ]

    table_rows = []

    for label, value in rows:
        table_rows.append(
            "<tr>"
            f"<th align='left'>{html.escape(str(label))}</th>"
            f"<td>{html.escape(str(value))}</td>"
            "</tr>"
        )

    return (
        "<h3>LADOT Speed Safety System</h3>"
        "<table>"
        + "".join(table_rows)
        + "</table>"
        "<p><strong>Geometry:</strong> Official LADOT published "
        "speed-safety corridor. This polygon does not represent "
        "an exact physical camera position.</p>"
        "<p><strong>Source:</strong> Los Angeles Department of "
        "Transportation Speed Safety System.</p>"
    )


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        return 1

    with INPUT_FILE.open(encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])

    if not features:
        print("ERROR: GeoJSON contains no features.")
        return 1

    root = ET.Element(kml_tag("kml"))
    document = ET.SubElement(root, kml_tag("Document"))

    add_text(document, "name", "LADOT Speed Safety Systems")

    add_text(
        document,
        "description",
        (
            "Official LADOT Speed Safety System corridors. "
            "Corridor polygons are sourced from the City of "
            "Los Angeles ArcGIS dataset."
        ),
    )

    # Shared polygon style.
    style = ET.SubElement(document, kml_tag("Style"), id="ladot-speed-safety")

    line_style = ET.SubElement(style, kml_tag("LineStyle"))
    add_text(line_style, "color", "ff0000ff")
    add_text(line_style, "width", "3")

    poly_style = ET.SubElement(style, kml_tag("PolyStyle"))
    add_text(poly_style, "color", "400000ff")
    add_text(poly_style, "fill", "1")
    add_text(poly_style, "outline", "1")

    written = 0

    for feature in features:
        properties = feature.get("properties", {})
        geometry = feature.get("geometry") or {}

        if geometry.get("type") != "Polygon":
            print(
                "ERROR: Unexpected geometry for OBJECTID "
                f"{properties.get('OBJECTID')}: "
                f"{geometry.get('type')}"
            )
            return 1

        rings = geometry.get("coordinates", [])

        if len(rings) != 1:
            print(
                "ERROR: Expected one polygon ring for OBJECTID "
                f"{properties.get('OBJECTID')}, got {len(rings)}"
            )
            return 1

        ring = rings[0]

        street = properties.get("StreetName", "Unknown Street")
        from_street = properties.get("XStreet2", "")
        to_street = properties.get("XStreet1", "")

        name = f"{street}: {from_street} to {to_street}"

        placemark = ET.SubElement(document, kml_tag("Placemark"))

        add_text(placemark, "name", name)
        add_text(placemark, "styleUrl", "#ladot-speed-safety")
        add_text(
            placemark,
            "description",
            make_description(properties),
        )

        extended = ET.SubElement(
            placemark,
            kml_tag("ExtendedData"),
        )

        for key, value in properties.items():
            data_element = ET.SubElement(
                extended,
                kml_tag("Data"),
                name=str(key),
            )

            value_element = ET.SubElement(
                data_element,
                kml_tag("value"),
            )

            if value is not None:
                value_element.text = str(value)

        polygon = ET.SubElement(placemark, kml_tag("Polygon"))

        add_text(polygon, "tessellate", "1")

        outer = ET.SubElement(
            polygon,
            kml_tag("outerBoundaryIs"),
        )

        linear_ring = ET.SubElement(
            outer,
            kml_tag("LinearRing"),
        )

        coordinates = ET.SubElement(
            linear_ring,
            kml_tag("coordinates"),
        )

        coordinates.text = "\n".join(
            f"{lon:.8f},{lat:.8f},0"
            for lon, lat in ring
        )

        written += 1

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    tree = ET.ElementTree(root)

    ET.indent(tree, space="  ")

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print(f"Read {len(features)} LADOT features.")
    print(f"Wrote {written} KML placemarks.")
    print(f"Wrote {OUTPUT_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
