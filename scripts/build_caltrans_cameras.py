#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests


BASE_DIR = Path("/var/www/html")
ATAK_DIR = BASE_DIR / "atak"
DATA_DIR = ATAK_DIR / "data"

OUTPUT_JSON = DATA_DIR / "caltrans-cameras.json"
OUTPUT_KML = ATAK_DIR / "caltrans-cameras.kml"
OUTPUT_NETWORK_KML = ATAK_DIR / "caltrans-network.kml"

PUBLIC_KML_URL = (
    "https://tim.workisboring.com/atak/caltrans-cameras.kml"
)

DISTRICTS = {
    7: "Los Angeles / Ventura",
    8: "San Bernardino / Riverside",
    11: "San Diego / Imperial",
    12: "Orange County",
}

FEED_URLS = {
    district: (
        "https://cwwp2.dot.ca.gov/"
        f"data/d{district}/cctv/cctvStatusD{district:02d}.json"
    )
    for district in DISTRICTS
}

USER_AGENT = (
    "tim.workisboring.com-public-camera-map/1.0 "
    "(https://tim.workisboring.com/atak/cameras.html)"
)


def normalized_key(value: object) -> str:
    """Normalize dictionary keys for tolerant matching."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def flatten_dict(
    value: Any,
    prefix: str = "",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten nested dictionaries while retaining normalized key paths."""
    if result is None:
        result = {}

    if isinstance(value, dict):
        for key, child in value.items():
            key_name = normalized_key(key)
            full_key = f"{prefix}{key_name}"

            if isinstance(child, dict):
                flatten_dict(child, f"{full_key}.", result)
            else:
                result[full_key] = child

                # Also store the final key independently.
                result.setdefault(key_name, child)

    return result


def first_value(
    flattened: dict[str, Any],
    candidate_keys: list[str],
) -> Any:
    """Find the first nonempty value matching a possible field name."""
    normalized_candidates = [
        normalized_key(candidate) for candidate in candidate_keys
    ]

    for candidate in normalized_candidates:
        for key, value in flattened.items():
            final_key = key.split(".")[-1]

            if (
                final_key == candidate
                or normalized_key(key) == candidate
                or normalized_key(key).endswith(candidate)
            ):
                if value not in (None, "", [], {}):
                    return value

    return None


def first_url(
    flattened: dict[str, Any],
    candidate_keys: list[str],
) -> str:
    value = first_value(flattened, candidate_keys)

    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.startswith(("http://", "https://")):
                return item
        return ""

    if isinstance(value, dict):
        nested = flatten_dict(value)
        for nested_value in nested.values():
            if isinstance(nested_value, str) and nested_value.startswith(
                ("http://", "https://")
            ):
                return nested_value
        return ""

    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value.strip()

    return ""


def as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number


def in_california(lat: float, lon: float) -> bool:
    return 32.3 <= lat <= 42.1 and -124.6 <= lon <= -114.0


def looks_like_camera_record(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    flattened = flatten_dict(value)

    lat = first_value(
        flattened,
        ["latitude", "lat", "ycoordinate", "y"],
    )
    lon = first_value(
        flattened,
        ["longitude", "lon", "lng", "xcoordinate", "x"],
    )

    return as_float(lat) is not None and as_float(lon) is not None


def find_camera_records(value: Any) -> list[dict[str, Any]]:
    """
    Locate camera records without depending on a single undocumented
    top-level JSON property.
    """
    records: list[dict[str, Any]] = []

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            if looks_like_camera_record(current):
                records.append(current)
                return

            for child in current.values():
                walk(child)

        elif isinstance(current, list):
            for child in current:
                walk(child)

    walk(value)
    return records


def stable_id(
    district: int,
    name: str,
    lat: float,
    lon: float,
    source_id: str,
) -> str:
    raw = f"{district}|{source_id}|{name}|{lat:.6f}|{lon:.6f}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]
    return f"caltrans-d{district}-{digest}"


def normalize_record(
    district: int,
    raw: dict[str, Any],
) -> dict[str, Any] | None:
    fields = flatten_dict(raw)

    lat = as_float(
        first_value(
            fields,
            ["latitude", "lat", "ycoordinate", "y"],
        )
    )
    lon = as_float(
        first_value(
            fields,
            ["longitude", "lon", "lng", "xcoordinate", "x"],
        )
    )

    if lat is None or lon is None:
        return None

    if not in_california(lat, lon):
        return None

    name = str(
        first_value(
            fields,
            [
                "locationname",
                "cctvlocation",
                "description",
                "name",
                "location",
                "nearbyplace",
            ],
        )
        or f"Caltrans District {district} Camera"
    ).strip()

    route = str(
        first_value(
            fields,
            ["route", "routename", "highway", "roadway"],
        )
        or ""
    ).strip()

    county = str(
        first_value(
            fields,
            ["county", "countyname"],
        )
        or ""
    ).strip()

    direction = str(
        first_value(
            fields,
            [
                "direction",
                "directionoftravel",
                "cameradirection",
                "viewdirection",
            ],
        )
        or ""
    ).strip()

    status = str(
        first_value(
            fields,
            ["status", "cctvstatus", "operationstatus"],
        )
        or ""
    ).strip()

    source_id = str(
        first_value(
            fields,
            [
                "index",
                "id",
                "cctvid",
                "deviceid",
                "stationid",
            ],
        )
        or ""
    ).strip()

    image_url = first_url(
        fields,
        [
            "imageurl",
            "imagehref",
            "stillimageurl",
            "snapshoturl",
            "currentimageurl",
            "thumbnailurl",
            "image",
        ],
    )

    stream_url = first_url(
        fields,
        [
            "streamingvideourl",
            "streamurl",
            "videourl",
            "liveurl",
        ],
    )

    public_url = first_url(
        fields,
        [
            "websiteurl",
            "webpageurl",
            "camerapageurl",
            "locationurl",
            "url",
        ],
    )

    # Avoid making a raw image the primary link when another page exists.
    if not public_url:
        public_url = stream_url or image_url or "https://video.dot.ca.gov/"

    display_name = name
    if route and route.lower() not in name.lower():
        display_name = f"{route} – {name}"

    return {
        "id": stable_id(
            district=district,
            name=display_name,
            lat=lat,
            lon=lon,
            source_id=source_id,
        ),
        "name": display_name,
        "source": "Caltrans CWWP2",
        "category": "Traffic Camera",
        "lat": lat,
        "lon": lon,
        "county": county,
        "heading": direction,
        "thumbnail": image_url,
        "url": public_url,
        "stream_url": stream_url,
        "stream_type": "external" if stream_url else "",
        "region": DISTRICTS[district],
        "district": district,
        "route": route,
        "status": status,
        "attribution": "Camera courtesy of Caltrans",
    }


def fetch_district(
    session: requests.Session,
    district: int,
) -> list[dict[str, Any]]:
    url = FEED_URLS[district]

    response = session.get(url, timeout=60)
    response.raise_for_status()

    payload = response.json()
    raw_records = find_camera_records(payload)

    cameras: list[dict[str, Any]] = []

    for raw in raw_records:
        camera = normalize_record(district, raw)
        if camera is not None:
            cameras.append(camera)

    print(
        f"District {district}: "
        f"{len(raw_records)} records found, "
        f"{len(cameras)} normalized"
    )

    return cameras


def deduplicate(
    cameras: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}

    for camera in cameras:
        key = camera["id"]
        unique[key] = camera

    return sorted(
        unique.values(),
        key=lambda camera: (
            int(camera.get("district", 0)),
            str(camera.get("name", "")).lower(),
        ),
    )


def write_json(cameras: list[dict[str, Any]]) -> None:
    payload = {
        "source_key": "caltrans",
        "title": "Caltrans Southern California Traffic Cameras",
        "generated_at": int(time.time()),
        "count": len(cameras),
        "cameras": cameras,
    }

    temporary = OUTPUT_JSON.with_suffix(".json.tmp")

    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    temporary.replace(OUTPUT_JSON)


def add_text(
    parent: ET.Element,
    tag: str,
    value: object,
) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = str(value)
    return element


def write_kml(cameras: list[dict[str, Any]]) -> None:
    kml = ET.Element(
        "kml",
        xmlns="http://www.opengis.net/kml/2.2",
    )
    document = ET.SubElement(kml, "Document")

    add_text(
        document,
        "name",
        "Caltrans Southern California Traffic Cameras",
    )

    style = ET.SubElement(document, "Style", id="camera-style")
    icon_style = ET.SubElement(style, "IconStyle")
    add_text(icon_style, "scale", "1.1")

    icon = ET.SubElement(icon_style, "Icon")
    add_text(
        icon,
        "href",
        "https://maps.google.com/mapfiles/kml/shapes/camera.png",
    )

    for district, district_name in DISTRICTS.items():
        folder = ET.SubElement(document, "Folder")
        add_text(
            folder,
            "name",
            f"District {district}: {district_name}",
        )

        for camera in cameras:
            if camera["district"] != district:
                continue

            placemark = ET.SubElement(folder, "Placemark")
            add_text(placemark, "name", camera["name"])
            add_text(placemark, "styleUrl", "#camera-style")

            description_lines = [
                f"<b>{html.escape(camera['name'])}</b>",
                f"Source: {html.escape(camera['source'])}",
                f"District: {camera['district']}",
            ]

            if camera.get("route"):
                description_lines.append(
                    f"Route: {html.escape(str(camera['route']))}"
                )

            if camera.get("county"):
                description_lines.append(
                    f"County: {html.escape(str(camera['county']))}"
                )

            if camera.get("status"):
                description_lines.append(
                    f"Status: {html.escape(str(camera['status']))}"
                )

            if camera.get("url"):
                safe_url = html.escape(str(camera["url"]), quote=True)
                description_lines.append(
                    f'<a href="{safe_url}">Open camera</a>'
                )

            if camera.get("thumbnail"):
                safe_image = html.escape(
                    str(camera["thumbnail"]),
                    quote=True,
                )
                description_lines.append(
                    f'<a href="{safe_image}">Open latest image</a>'
                )
                description_lines.append(
                    f'<br><img src="{safe_image}" width="320">'
                )

            description_lines.append(
                "Camera courtesy of Caltrans"
            )

            description = "<br>".join(description_lines)
            add_text(placemark, "description", description)

            point = ET.SubElement(placemark, "Point")
            add_text(
                point,
                "coordinates",
                f"{camera['lon']},{camera['lat']},0",
            )

    temporary = OUTPUT_KML.with_suffix(".kml.tmp")

    ET.ElementTree(kml).write(
        temporary,
        encoding="utf-8",
        xml_declaration=True,
    )

    temporary.replace(OUTPUT_KML)


def write_network_kml() -> None:
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Caltrans Southern California Cameras Auto Refresh</name>
    <NetworkLink>
      <name>Caltrans Southern California Traffic Cameras</name>
      <refreshVisibility>1</refreshVisibility>
      <Link>
        <href>{PUBLIC_KML_URL}</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>900</refreshInterval>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""

    OUTPUT_NETWORK_KML.write_text(
        content,
        encoding="utf-8",
    )


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
    )

    cameras: list[dict[str, Any]] = []
    failures: list[str] = []

    for district in DISTRICTS:
        try:
            cameras.extend(fetch_district(session, district))
        except (
            requests.RequestException,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            failures.append(f"District {district}: {exc}")
            print(
                f"District {district} failed: {exc}",
                file=sys.stderr,
            )

    cameras = deduplicate(cameras)

    if not cameras:
        print(
            "No Caltrans cameras were generated. "
            "Existing output files were preserved.",
            file=sys.stderr,
        )
        return 1

    write_json(cameras)
    write_kml(cameras)
    write_network_kml()

    print(f"Wrote {OUTPUT_JSON} with {len(cameras)} cameras")
    print(f"Wrote {OUTPUT_KML}")
    print(f"Wrote {OUTPUT_NETWORK_KML}")

    if failures:
        print("Completed with partial failures:")
        for failure in failures:
            print(f"  {failure}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
