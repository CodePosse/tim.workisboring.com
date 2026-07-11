#!/usr/bin/env python3
"""
Download the DeFlock US KML and generate a California-only feed.

Outputs:
  /var/www/html/atak/data/deflock-california.json
  /var/www/html/atak/data/kml/deflock-california.kml
  /var/www/html/atak/data/kml/deflock-california-network.kml

Existing feeds are not modified.
"""

from __future__ import annotations

import copy
import html
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests


SOURCE_URL = (
    "http://training.gotak.cloud:3000/deflock_us_conus.kml"
)

PUBLIC_BASE_URL = "https://tim.workisboring.com"

ATAK_DIRECTORY = Path("/var/www/html/atak")
DATA_DIRECTORY = ATAK_DIRECTORY / "data"
KML_DIRECTORY = DATA_DIRECTORY / "kml"

JSON_FILE = DATA_DIRECTORY / "deflock-socal.json"
KML_FILE = KML_DIRECTORY / "deflock-socal.kml"
NETWORK_FILE = KML_DIRECTORY / "deflock-socal-network.kml"

# Broad California bounding box.
SOCAL_MIN_LAT = 32.3
SOCAL_MAX_LAT = 35.9
SOCAL_MIN_LON = -121.0
SOCAL_MAX_LON = -114.0

REQUEST_TIMEOUT = 180

KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
GX_NAMESPACE = "http://www.google.com/kml/ext/2.2"

NS = {
    "kml": KML_NAMESPACE,
    "gx": GX_NAMESPACE,
}

ET.register_namespace("", KML_NAMESPACE)
ET.register_namespace("gx", GX_NAMESPACE)


def log(message: str) -> None:
    print(message, flush=True)


def tag(name: str) -> str:
    return f"{{{KML_NAMESPACE}}}{name}"


def download_source() -> bytes:
    response = requests.get(
        SOURCE_URL,
        timeout=REQUEST_TIMEOUT,
        headers={
            "Accept": (
                "application/vnd.google-earth.kml+xml,"
                "application/xml,text/xml,*/*"
            ),
            "User-Agent": "SoCal-TAK-DeFlock/1.0",
        },
    )

    response.raise_for_status()

    body = response.content

    if (
        b"<kml" not in body
        and b"<Document" not in body
        and b"<Placemark" not in body
    ):
        raise RuntimeError(
            "Downloaded response does not appear to be KML."
        )

    return body


def parse_coordinate_text(
    coordinate_text: str | None,
) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []

    if not coordinate_text:
        return coordinates

    for entry in coordinate_text.replace("\n", " ").split():
        parts = entry.split(",")

        if len(parts) < 2:
            continue

        try:
            longitude = float(parts[0])
            latitude = float(parts[1])
        except ValueError:
            continue

        coordinates.append((latitude, longitude))

    return coordinates


def placemark_coordinates(
    placemark: ET.Element,
) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []

    # Point, LineString, Polygon and MultiGeometry coordinates.
    for element in placemark.findall(".//kml:coordinates", NS):
        coordinates.extend(parse_coordinate_text(element.text))

    # gx:Track coordinates use "longitude latitude altitude".
    for element in placemark.findall(".//gx:coord", NS):
        if not element.text:
            continue

        parts = element.text.strip().split()

        if len(parts) < 2:
            continue

        try:
            longitude = float(parts[0])
            latitude = float(parts[1])
        except ValueError:
            continue

        coordinates.append((latitude, longitude))

    return coordinates


def is_in_southern_california(
    latitude: float,
    longitude: float,
) -> bool:
    return (
        SOCAL_MIN_LAT <= latitude <= SOCAL_MAX_LAT
        and SOCAL_MIN_LON <= longitude <= SOCAL_MAX_LON
    )

def placemark_is_in_southern_california(
    placemark: ET.Element,
) -> bool:
    coordinates = placemark_coordinates(placemark)

    return any(
        is_in_southern_california(latitude, longitude)
        for latitude, longitude in coordinates
    )


def first_coordinate(
    placemark: ET.Element,
) -> tuple[float, float] | None:
    for latitude, longitude in placemark_coordinates(placemark):
        if is_in_southern_california(latitude, longitude):
            return latitude, longitude

    return None


def child_text(
    parent: ET.Element,
    child_name: str,
    default: str = "",
) -> str:
    child = parent.find(f"kml:{child_name}", NS)

    if child is None or child.text is None:
        return default

    return child.text.strip()


def extended_data(placemark: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}

    for data_element in placemark.findall(
        ".//kml:ExtendedData/kml:Data",
        NS,
    ):
        name = data_element.attrib.get("name", "").strip()

        value_element = data_element.find("kml:value", NS)
        value = (
            value_element.text.strip()
            if value_element is not None
            and value_element.text
            else ""
        )

        if name:
            values[name] = value

    for simple_data in placemark.findall(
        ".//kml:ExtendedData/"
        "kml:SchemaData/kml:SimpleData",
        NS,
    ):
        name = simple_data.attrib.get("name", "").strip()
        value = (
            simple_data.text.strip()
            if simple_data.text
            else ""
        )

        if name:
            values[name] = value

    return values


def normalized_camera(
    placemark: ET.Element,
    index: int,
) -> dict[str, Any] | None:
    coordinate = first_coordinate(placemark)

    if coordinate is None:
        return None

    latitude, longitude = coordinate
    metadata = extended_data(placemark)

    name = child_text(
        placemark,
        "name",
        f"DeFlock Camera {index}",
    )

    description = child_text(
        placemark,
        "description",
        "",
    )

    placemark_id = placemark.attrib.get(
        "id",
        f"{latitude}-{longitude}-{index}",
    )

    return {
        "id": f"deflock-{placemark_id}",
        "name": name,
        "source": "DeFlock",
        "category": "🚨 ALPR Camera Location",
        "lat": latitude,
        "lon": longitude,
        "county": metadata.get(
            "county",
            metadata.get("County", ""),
        ),
        "city": metadata.get(
            "city",
            metadata.get("City", ""),
        ),
        "heading": "",
        "thumbnail": "",
        "url": "https://maps.deflock.org/",
        "description": description,
        "metadata": metadata,
        "attribution": "Camera-location data provided by DeFlock",
    }


def source_document(root: ET.Element) -> ET.Element:
    document = root.find("kml:Document", NS)

    if document is not None:
        return document

    # Some KMLs wrap Document in another element.
    document = root.find(".//kml:Document", NS)

    if document is None:
        raise RuntimeError("The source KML has no Document element.")

    return document


def create_filtered_kml(
    source_root: ET.Element,
    selected_placemarks: list[ET.Element],
) -> ET.ElementTree:
    source_doc = source_document(source_root)

    output_root = ET.Element(tag("kml"))
    output_document = ET.SubElement(output_root, tag("Document"))

    ET.SubElement(
        output_document,
        tag("name"),
    ).text = "DeFlock Southern California ALPR Camera Locations"

    ET.SubElement(
        output_document,
        tag("description"),
    ).text = (
        "Southern California-only ALPR camera-location layer filtered "
        "from the DeFlock CONUS KML."
    )

    # Copy styles and schemas so referenced marker styles still work.
    reusable_tags = {
        tag("Style"),
        tag("StyleMap"),
        tag("Schema"),
    }

    for child in list(source_doc):
        if child.tag in reusable_tags:
            output_document.append(copy.deepcopy(child))

    folder = ET.SubElement(output_document, tag("Folder"))

    ET.SubElement(
        folder,
        tag("name"),
    ).text = "Southern California DeFlock Camera Locations"

    for placemark in selected_placemarks:
        folder.append(copy.deepcopy(placemark))

    return ET.ElementTree(output_root)


def write_json(cameras: list[dict[str, Any]]) -> None:
    payload = {
        "source_key": "deflock",
        "title": "DeFlock Southern California ALPR Camera Locations",
        "generated_at": int(time.time()),
        "count": len(cameras),
        "attribution": "Camera-location data provided by DeFlock",
        "cameras": cameras,
    }

    temporary = JSON_FILE.with_suffix(".json.tmp")

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    temporary.replace(JSON_FILE)


def write_filtered_kml(tree: ET.ElementTree) -> None:
    temporary = KML_FILE.with_suffix(".kml.tmp")

    tree.write(
        temporary,
        encoding="utf-8",
        xml_declaration=True,
    )

    temporary.replace(KML_FILE)


def write_network_kml() -> None:
    target_url = (
    f"{PUBLIC_BASE_URL}"
    "/atak/data/kml/deflock-socal.kml"
)

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>DeFlock Southern California ALPR Camera Locations</name>

    <NetworkLink>
      <name>DeFlock Southern California ALPR Camera Locations</name>
      <refreshVisibility>1</refreshVisibility>
      <flyToView>0</flyToView>

      <Link>
        <href>{html.escape(target_url)}</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>86400</refreshInterval>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""

    NETWORK_FILE.write_text(content, encoding="utf-8")


def main() -> int:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    KML_DIRECTORY.mkdir(parents=True, exist_ok=True)

    log(f"Downloading: {SOURCE_URL}")

    source_bytes = download_source()
    source_root = ET.fromstring(source_bytes)

    all_placemarks = source_root.findall(
        ".//kml:Placemark",
        NS,
    )

    selected_placemarks: list[ET.Element] = []
    cameras: list[dict[str, Any]] = []

    for index, placemark in enumerate(
        all_placemarks,
        start=1,
    ):
        if not placemark_is_in_southern_california(placemark):
            continue

        selected_placemarks.append(placemark)

        camera = normalized_camera(placemark, index)

        if camera is not None:
            cameras.append(camera)

    log(f"Source placemarks: {len(all_placemarks)}")
    log(f"Southern California placemarks: {len(selected_placemarks)}")

    if not selected_placemarks:
        if KML_FILE.exists() and JSON_FILE.exists():
            log(
                "No Southern California placemarks returned; preserving "
                "the previous files."
            )
            return 0

        raise RuntimeError(
            "No Southern California placemarks were found."
        )

    filtered_tree = create_filtered_kml(
        source_root,
        selected_placemarks,
    )

    write_json(cameras)
    write_filtered_kml(filtered_tree)
    write_network_kml()

    log(f"Wrote: {JSON_FILE}")
    log(f"Wrote: {KML_FILE}")
    log(f"Wrote: {NETWORK_FILE}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.RequestException as error:
        print(f"DeFlock download failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        print(f"DeFlock build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
