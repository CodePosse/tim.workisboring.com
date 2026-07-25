#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests


PUBLIC_BASE_URL = "https://tim.workisboring.com"

ATAK_DIRECTORY = Path("/var/www/html/atak")
DATA_DIRECTORY = ATAK_DIRECTORY / "data"
KML_DIRECTORY = DATA_DIRECTORY / "kml"

DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
KML_DIRECTORY.mkdir(parents=True, exist_ok=True)

SOCAL_BBOX = {
    "xmin": -121.0,
    "ymin": 32.3,
    "xmax": -114.0,
    "ymax": 36.8,
    "spatialReference": {"wkid": 4326},
}

ALERTWEST_API = (
    "https://api.cdn.prod.alertwest.com/api/firecams/v0/cameras"
)

CALOES_API = (
    "https://services.arcgis.com/BLN4oKB0N1YSgvY8/"
    "arcgis/rest/services/CalOES_California_Webcams/"
    "FeatureServer/0/query"
)

USGS_API = "https://api.waterdata.usgs.gov/nims/v0/cameras"

SOURCES = {
    "alertwest": {
        "title": "ALERTCalifornia / AlertWest Cameras",
        "json": "alertwest-cameras.json",
        "kml": "alertca.kml",
        "network": "alertca-network.kml",
    },
    "caloes-fire": {
        "title": "Cal OES Fire Cameras",
        "json": "caloes-fire-cameras.json",
        "kml": "caloes-fire-cameras.kml",
        "network": "caloes-fire-network.kml",
    },
    "caloes-traffic": {
        "title": "Cal OES Traffic Cameras",
        "json": "caloes-traffic-cameras.json",
        "kml": "caloes-traffic-cameras.kml",
        "network": "caloes-traffic-network.kml",
    },
    "usgs": {
        "title": "USGS California River and Water Cameras",
        "json": "usgs-cameras.json",
        "kml": "usgs-cameras.kml",
        "network": "usgs-network.kml",
    },
}

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "SoCal-TAK/1.0",
})


def pick(
    data: Any,
    keys: list[str],
    default: Any = "",
) -> Any:
    if not isinstance(data, dict):
        return default

    for key in keys:
        value = data.get(key)

        if value not in (None, "", []):
            return value

    return default


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
) -> Any:
    response = SESSION.get(
        url,
        params=params,
        timeout=45,
    )

    response.raise_for_status()
    return response.json()


def arcgis_params() -> dict[str, str]:
    return {
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "geometry": json.dumps(SOCAL_BBOX),
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "resultRecordCount": "3000",
    }


def write_json(
    source_key: str,
    cameras: list[dict[str, Any]],
) -> None:
    source = SOURCES[source_key]
    destination = DATA_DIRECTORY / source["json"]

    payload = {
        "source_key": source_key,
        "title": source["title"],
        "generated_at": int(time.time()),
        "count": len(cameras),
        "cameras": cameras,
    }

    temporary = destination.with_suffix(".json.tmp")

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    temporary.replace(destination)


def description_html(camera: dict[str, Any]) -> str:
    parts = [
        f"<b>{html.escape(str(camera.get('name', 'Camera')))}</b><br>",
        (
            "Type: "
            f"{html.escape(str(camera.get('category', '')))}<br>"
        ),
        (
            "Source: "
            f"{html.escape(str(camera.get('source', '')))}<br>"
        ),
    ]

    if camera.get("county"):
        parts.append(
            f"County: {html.escape(str(camera['county']))}<br>"
        )

    if camera.get("heading") not in (None, ""):
        parts.append(
            f"View: {html.escape(str(camera['heading']))}°<br>"
        )

    if camera.get("url"):
        parts.append(
            '<a href="'
            f'{html.escape(str(camera["url"]))}'
            '">Open camera page</a><br>'
        )

    if camera.get("timelapse"):
        parts.append(
            '<a href="'
            f'{html.escape(str(camera["timelapse"]))}'
            '">Open timelapse</a><br>'
        )

    if camera.get("thumbnail"):
        thumbnail = html.escape(str(camera["thumbnail"]))
        parts.append(
            f'<a href="{thumbnail}">Open latest image</a><br>'
            f'<img src="{thumbnail}" width="320"><br>'
        )

    return "<![CDATA[" + "".join(parts) + "]]>"


def write_kml(
    source_key: str,
    cameras: list[dict[str, Any]],
) -> None:
    source = SOURCES[source_key]
    destination = KML_DIRECTORY / source["kml"]

    kml = ET.Element(
        "kml",
        xmlns="http://www.opengis.net/kml/2.2",
    )

    document = ET.SubElement(kml, "Document")
    ET.SubElement(document, "name").text = source["title"]

    style = ET.SubElement(
        document,
        "Style",
        id="camera-style",
    )

    icon_style = ET.SubElement(style, "IconStyle")
    ET.SubElement(icon_style, "scale").text = "1.1"

    icon = ET.SubElement(icon_style, "Icon")
    ET.SubElement(icon, "href").text = (
        "https://maps.google.com/mapfiles/kml/shapes/camera.png"
    )

    folder = ET.SubElement(document, "Folder")
    ET.SubElement(folder, "name").text = source["title"]

    for camera in cameras:
        latitude = as_float(camera.get("lat"))
        longitude = as_float(camera.get("lon"))

        if latitude is None or longitude is None:
            continue

        placemark = ET.SubElement(folder, "Placemark")

        ET.SubElement(
            placemark,
            "name",
        ).text = str(camera.get("name", "Camera"))

        ET.SubElement(
            placemark,
            "styleUrl",
        ).text = "#camera-style"

        ET.SubElement(
            placemark,
            "description",
        ).text = description_html(camera)

        point = ET.SubElement(placemark, "Point")

        ET.SubElement(
            point,
            "coordinates",
        ).text = f"{longitude},{latitude},0"

    temporary = destination.with_suffix(".kml.tmp")

    ET.ElementTree(kml).write(
        temporary,
        encoding="utf-8",
        xml_declaration=True,
    )

    temporary.replace(destination)


def write_network_kml(source_key: str) -> None:
    source = SOURCES[source_key]
    destination = KML_DIRECTORY / source["network"]

    target_url = (
        f"{PUBLIC_BASE_URL}/atak/data/kml/{source['kml']}"
    )

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{html.escape(source["title"])}</name>
    <NetworkLink>
      <name>{html.escape(source["title"])}</name>
      <refreshVisibility>1</refreshVisibility>
      <Link>
        <href>{target_url}</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>900</refreshInterval>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""

    destination.write_text(content, encoding="utf-8")


def write_source(
    source_key: str,
    cameras: list[dict[str, Any]],
) -> None:
    if not cameras:
        json_path = DATA_DIRECTORY / SOURCES[source_key]["json"]
        kml_path = KML_DIRECTORY / SOURCES[source_key]["kml"]

        if json_path.exists() and kml_path.exists():
            print(
                f"{source_key}: 0 returned; preserving existing feed"
            )
            write_network_kml(source_key)
            return

    write_json(source_key, cameras)
    write_kml(source_key, cameras)
    write_network_kml(source_key)

    print(f"{source_key}: {len(cameras)}")


def fetch_alertwest() -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    payload = request_json(ALERTWEST_API)

    if not isinstance(payload, list):
        return cameras

    for camera in payload:
        if not isinstance(camera, dict):
            continue

        site = camera.get("site")
        image = camera.get("image")
        position = camera.get("position")

        if not isinstance(site, dict):
            site = {}

        if not isinstance(image, dict):
            image = {}

        if not isinstance(position, dict):
            position = {}

        latitude = as_float(site.get("latitude"))
        longitude = as_float(site.get("longitude"))

        if latitude is None or longitude is None:
            continue

        image_url = str(
            pick(image, ["url", "thumbnail"], "")
        )

        cameras.append({
            "id": (
                "alertwest-"
                + str(
                    pick(
                        camera,
                        ["id", "name"],
                        f"{latitude}-{longitude}",
                    )
                )
            ),
            "name": str(
                pick(
                    camera,
                    ["name"],
                    "ALERTCalifornia Camera",
                )
            ),
            "source": "ALERTCalifornia / AlertWest",
            "category": "🔥 Fire Camera",
            "lat": latitude,
            "lon": longitude,
            "county": str(pick(site, ["county"], "")),
            "heading": pick(position, ["pan"], ""),
            "thumbnail": image_url,
            "url": image_url or "https://alertcalifornia.org/",
        })

    return cameras


def classify_caloes(
    attributes: dict[str, Any],
) -> tuple[str | None, str | None]:
    text = " ".join([
        str(pick(attributes, ["CameraType"], "")),
        str(pick(attributes, ["Display_Type"], "")),
        str(pick(attributes, ["Source"], "")),
        str(pick(attributes, ["Location"], "")),
        str(pick(attributes, ["Webcam_URL"], "")),
        str(pick(attributes, ["Consolidated_URL"], "")),
    ]).lower()

    if "alert" in text or "fire" in text:
        return "caloes-fire", "🔥 Fire Camera"

    if any(
        keyword in text
        for keyword in (
            "traffic",
            "caltrans",
            "road",
            "highway",
            "freeway",
        )
    ):
        return "caloes-traffic", "🚗 Traffic Camera"

    return None, None


def fetch_caloes() -> dict[str, list[dict[str, Any]]]:
    buckets = {
        "caloes-fire": [],
        "caloes-traffic": [],
    }

    payload = request_json(
        CALOES_API,
        params=arcgis_params(),
    )

    if not isinstance(payload, dict):
        return buckets

    for feature in payload.get("features", []):
        if not isinstance(feature, dict):
            continue

        attributes = feature.get("attributes")
        geometry = feature.get("geometry")

        if not isinstance(attributes, dict):
            attributes = {}

        if not isinstance(geometry, dict):
            geometry = {}

        latitude = as_float(geometry.get("y"))
        longitude = as_float(geometry.get("x"))

        if latitude is None or longitude is None:
            continue

        source_key, category = classify_caloes(attributes)

        if not source_key or not category:
            continue

        buckets[source_key].append({
            "id": (
                "caloes-"
                + str(
                    pick(
                        attributes,
                        ["OBJECTID", "GlobalID"],
                        f"{latitude}-{longitude}",
                    )
                )
            ),
            "name": str(
                pick(
                    attributes,
                    ["Location", "Name", "NAME"],
                    "Cal OES Webcam",
                )
            ),
            "source": str(
                pick(attributes, ["Source"], "Cal OES")
            ),
            "category": category,
            "lat": latitude,
            "lon": longitude,
            "county": str(
                pick(attributes, ["County"], "")
            ).title(),
            "heading": pick(
                attributes,
                ["View_Degrees"],
                "",
            ),
            "thumbnail": str(
                pick(
                    attributes,
                    ["Thumbnail_Url"],
                    "",
                )
            ),
            "url": str(
                pick(
                    attributes,
                    [
                        "Webcam_URL",
                        "Consolidated_URL",
                        "Source_URL",
                    ],
                    "",
                )
            ),
        })

    return buckets


def in_california(latitude: float, longitude: float) -> bool:
    return (
        32.3 <= latitude <= 42.1
        and -124.6 <= longitude <= -114.0
    )


def fetch_usgs() -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    payload = request_json(USGS_API)

    if isinstance(payload, dict):
        payload = (
            payload.get("cameras")
            or payload.get("items")
            or payload.get("data")
            or []
        )

    if not isinstance(payload, list):
        return cameras

    for camera in payload:
        if not isinstance(camera, dict):
            continue

        if camera.get("hideCam"):
            continue

        state = str(
            pick(
                camera,
                ["stateAbrv", "state", "stateCode"],
                "",
            )
        ).upper()

        if state and state not in {"CA", "CALIFORNIA"}:
            continue

        latitude = as_float(
            pick(camera, ["lat", "latitude"], None)
        )

        longitude = as_float(
            pick(
                camera,
                ["lng", "lon", "longitude"],
                None,
            )
        )

        if latitude is None or longitude is None:
            continue

        if not in_california(latitude, longitude):
            continue

        camera_id = str(
            pick(
                camera,
                ["camId", "cameraId", "id"],
                f"{latitude}-{longitude}",
            )
        )

        thumbnail_directory = str(
            pick(camera, ["thumbDir"], "")
        )

        small_directory = str(
            pick(camera, ["smallDir"], "")
        )

        overlay_directory = str(
            pick(camera, ["overlayDir"], "")
        )

        timelapse_directory = str(
            pick(camera, ["tlDir"], "")
        )

        thumbnail = (
            f"{thumbnail_directory}{camera_id}_newest.jpg"
            if thumbnail_directory
            else ""
        )

        image_url = (
            f"{small_directory or overlay_directory}"
            f"{camera_id}_newest.jpg"
            if small_directory or overlay_directory
            else ""
        )

        timelapse = (
            f"{timelapse_directory}{camera_id}.mp4"
            if timelapse_directory
            else ""
        )

        cameras.append({
            "id": f"usgs-{camera_id}",
            "name": str(
                pick(
                    camera,
                    ["camName", "cameraName", "name"],
                    "USGS Camera",
                )
            ),
            "source": "USGS NIMS",
            "category": "🌊 River / Water Camera",
            "lat": latitude,
            "lon": longitude,
            "county": "",
            "heading": "",
            "thumbnail": thumbnail or image_url,
            "url": image_url or timelapse,
            "timelapse": timelapse,
        })

    return cameras


def main() -> int:
    try:
        write_source("alertwest", fetch_alertwest())
    except Exception as error:
        print(f"alertwest failed: {error}")

    try:
        caloes = fetch_caloes()

        write_source(
            "caloes-fire",
            caloes["caloes-fire"],
        )

        write_source(
            "caloes-traffic",
            caloes["caloes-traffic"],
        )
    except Exception as error:
        print(f"caloes failed: {error}")

    try:
        write_source("usgs", fetch_usgs())
    except Exception as error:
        print(f"usgs failed: {error}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
