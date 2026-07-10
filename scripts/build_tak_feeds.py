#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


API_BASE = "https://openwebcamdb.com/api/v1/"
PUBLIC_BASE_URL = "https://tim.workisboring.com"

OUT_DIR = Path("/var/www/html/atak")
DATA_DIR = OUT_DIR / "data"

JSON_FILE = DATA_DIR / "openwebcamdb-cameras.json"
KML_FILE = OUT_DIR / "openwebcamdb-cameras.kml"
NETWORK_FILE = OUT_DIR / "openwebcamdb-network.kml"

API_KEY = os.getenv("OPENWEBCAMDB_API_KEY", "").strip()

# California geographic envelope.
CA_SOUTH = 32.3
CA_NORTH = 42.1
CA_WEST = -124.6
CA_EAST = -114.0

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "SoCal-TAK/1.0",
})


def pick(data: Any, keys: list[str], default: Any = "") -> Any:
    if not isinstance(data, dict):
        return default

    for key in keys:
        value = data.get(key)

        if value not in (None, "", []):
            return value

    return default


def nested(data: Any, paths: list[tuple[str, ...]], default: Any = "") -> Any:
    for path in paths:
        value = data

        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break

            value = value[key]

        if value not in (None, "", []):
            return value

    return default


def request_json(
    path_or_url: str,
    params: dict[str, Any] | None = None,
) -> Any:
    if not API_KEY:
        raise RuntimeError(
            "OPENWEBCAMDB_API_KEY is not exported. "
            "Run: source /etc/socal-tak.env"
        )

    if path_or_url.startswith(("https://", "http://")):
        url = path_or_url
    else:
        url = urljoin(API_BASE, path_or_url.lstrip("/"))

    max_attempts = 5

    for attempt in range(1, max_attempts + 1):
        response = SESSION.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=REQUEST_TIMEOUT,
        )

        log(f"GET {response.url} -> HTTP {response.status_code}")

        if response.status_code == 429:
            try:
                payload = response.json()
            except ValueError:
                payload = {}

            retry_after = payload.get("retry_after")

            if retry_after is None:
                retry_after = response.headers.get("Retry-After", 60)

            try:
                retry_after = int(retry_after)
            except (TypeError, ValueError):
                retry_after = 60

            retry_after = max(retry_after, 5)

            if attempt >= max_attempts:
                raise RuntimeError(
                    f"OpenWebcamDB rate limit persisted after "
                    f"{max_attempts} attempts."
                )

            log(
                f"Rate limited. Waiting {retry_after + 2} seconds "
                f"before retry {attempt + 1}/{max_attempts}."
            )

            time.sleep(retry_after + 2)
            continue

        response.raise_for_status()

        try:
            return response.json()
        except ValueError as exc:
            preview = response.text[:500]
            raise RuntimeError(
                f"OpenWebcamDB returned invalid JSON: {preview}"
            ) from exc

    raise RuntimeError("OpenWebcamDB request failed unexpectedly.")

def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("webcams", "data", "items", "results"):
        value = payload.get(key)

        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

        if isinstance(value, dict):
            for nested_key in ("webcams", "items", "results", "data"):
                nested_value = value.get(nested_key)

                if isinstance(nested_value, list):
                    return [
                        item
                        for item in nested_value
                        if isinstance(item, dict)
                    ]

    return []


def extract_next_page(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    direct = pick(payload, ["next", "next_page", "nextPage"], None)

    if isinstance(direct, str) and direct:
        return direct

    for container_key in ("links", "pagination", "meta"):
        container = payload.get(container_key)

        if not isinstance(container, dict):
            continue

        next_value = pick(
            container,
            ["next", "next_page", "nextPage", "next_url"],
            None,
        )

        if isinstance(next_value, str) and next_value:
            return next_value

    return None


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coordinates(camera: dict[str, Any]) -> tuple[float | None, float | None]:
    location = camera.get("location")
    if not isinstance(location, dict):
        location = {}

    lat = pick(
        camera,
        ["latitude", "lat"],
        pick(location, ["latitude", "lat"], None),
    )

    lon = pick(
        camera,
        ["longitude", "lon", "lng"],
        pick(location, ["longitude", "lon", "lng"], None),
    )

    return as_float(lat), as_float(lon)


def is_california(camera: dict[str, Any], lat: float, lon: float) -> bool:
    location = camera.get("location")
    if not isinstance(location, dict):
        location = {}

    state = str(
        pick(
            camera,
            ["state", "state_code", "region"],
            pick(location, ["state", "state_code", "region"], ""),
        )
    ).strip().lower()

    country = str(
        pick(
            camera,
            ["country", "country_code"],
            pick(location, ["country", "country_code"], ""),
        )
    ).strip().lower()

    if country and country not in (
        "us",
        "usa",
        "united states",
        "united states of america",
    ):
        return False

    if state and state not in ("ca", "california"):
        return False

    return (
        CA_SOUTH <= lat <= CA_NORTH
        and CA_WEST <= lon <= CA_EAST
    )


def fetch_detail(summary: dict[str, Any]) -> dict[str, Any]:
    slug = str(pick(summary, ["slug"], "")).strip()

    if not slug:
        return summary

    try:
        detail = request_json(f"webcams/{slug}")
    except requests.RequestException as exc:
        print(f"Detail request failed for {slug}: {exc}", file=sys.stderr)
        return summary

    if isinstance(detail, dict):
        for key in ("webcam", "data", "result"):
            if isinstance(detail.get(key), dict):
                return detail[key]

        return detail

    return summary


def category_text(camera: dict[str, Any]) -> str:
    categories = camera.get("categories", [])

    if isinstance(categories, list):
        names: list[str] = []

        for item in categories:
            if isinstance(item, dict):
                name = pick(item, ["name", "title", "slug"], "")
            else:
                name = str(item)

            if name:
                names.append(str(name))

        if names:
            return ", ".join(names)

    if isinstance(categories, str) and categories:
        return categories

    return str(pick(camera, ["category", "type"], "Tourist Webcam"))


def normalize(camera: dict[str, Any]) -> dict[str, Any] | None:
    lat, lon = coordinates(camera)

    if lat is None or lon is None:
        return None

    if not is_california(camera, lat, lon):
        return None

    location = camera.get("location")
    if not isinstance(location, dict):
        location = {}

    slug = str(pick(camera, ["slug"], f"{lat}-{lon}"))

    thumbnail = nested(
        camera,
        [
            ("images", "thumbnail"),
            ("images", "preview"),
            ("image", "thumbnail"),
            ("image", "preview"),
            ("image", "url"),
            ("thumbnail",),
            ("thumbnail_url",),
            ("preview",),
            ("preview_url",),
        ],
        "",
    )

    page_url = nested(
        camera,
        [
            ("urls", "detail"),
            ("urls", "web"),
            ("page_url",),
            ("webcam_url",),
            ("url",),
        ],
        "",
    )

    if not page_url and slug:
        page_url = f"https://openwebcamdb.com/webcams/{slug}"

    stream_url = str(
        pick(
            camera,
            ["stream_url", "streamUrl", "live_url"],
            "",
        )
    )

    city = str(
        pick(
            camera,
            ["city"],
            pick(location, ["city"], ""),
        )
    )

    county = str(
        pick(
            camera,
            ["county"],
            pick(location, ["county"], ""),
        )
    )

    return {
        "id": f"openwebcamdb-{slug}",
        "slug": slug,
        "name": str(
            pick(
                camera,
                ["title", "name"],
                "OpenWebcamDB Camera",
            )
        ),
        "source": "OpenWebcamDB",
        "category": f"🏖️ {category_text(camera)}",
        "lat": lat,
        "lon": lon,
        "county": county,
        "city": city,
        "heading": "",
        "thumbnail": str(thumbnail or ""),
        # Prefer the public detail page. Keep the stream separately.
        "url": str(page_url or ""),
        "stream_url": stream_url,
        "attribution": "Powered by OpenWebcamDB.com",
    }


def fetch_summaries() -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    next_url: str | None = "webcams"
    page = 1

    while next_url and page <= 20:
        params = None

        if next_url == "webcams":
            params = {
                "limit": 100,
                "page": page,
            }

        payload = request_json(next_url, params=params)
        items = extract_items(payload)

        if not items:
            break

        new_items = 0

        for item in items:
            slug = str(pick(item, ["slug"], "")).strip()

            if slug and slug in seen_slugs:
                continue

            if slug:
                seen_slugs.add(slug)

            all_items.append(item)
            new_items += 1

        explicit_next = extract_next_page(payload)

        if explicit_next:
            next_url = explicit_next
        elif len(items) >= 100 and new_items:
            page += 1
            next_url = "webcams"
        else:
            next_url = None

    return all_items


def fetch_cameras() -> list[dict[str, Any]]:
    summaries = fetch_summaries()
    cameras: list[dict[str, Any]] = []

    for summary in summaries:
        lat, lon = coordinates(summary)

        # Avoid spending detail requests on obviously non-California cameras.
        if lat is not None and lon is not None:
            if not is_california(summary, lat, lon):
                continue

        detail = fetch_detail(summary)
        camera = normalize(detail)

        if camera:
            cameras.append(camera)

    cameras.sort(key=lambda item: (item["name"].lower(), item["id"]))
    return cameras


def write_json(cameras: list[dict[str, Any]]) -> None:
    payload = {
        "source_key": "openwebcamdb",
        "title": "OpenWebcamDB California Cameras",
        "generated_at": int(time.time()),
        "count": len(cameras),
        "attribution": "Powered by OpenWebcamDB.com",
        "cameras": cameras,
    }

    temporary = JSON_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(JSON_FILE)


def write_kml(cameras: list[dict[str, Any]]) -> None:
    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    document = ET.SubElement(kml, "Document")
    ET.SubElement(document, "name").text = (
        "OpenWebcamDB California Cameras"
    )

    style = ET.SubElement(document, "Style", id="openwebcam-camera")
    icon_style = ET.SubElement(style, "IconStyle")
    ET.SubElement(icon_style, "scale").text = "1.1"

    icon = ET.SubElement(icon_style, "Icon")
    ET.SubElement(icon, "href").text = (
        "https://maps.google.com/mapfiles/kml/shapes/camera.png"
    )

    folder = ET.SubElement(document, "Folder")
    ET.SubElement(folder, "name").text = (
        "OpenWebcamDB California Cameras"
    )

    for camera in cameras:
        placemark = ET.SubElement(folder, "Placemark")
        ET.SubElement(placemark, "name").text = camera["name"]
        ET.SubElement(placemark, "styleUrl").text = "#openwebcam-camera"

        description = f"""<![CDATA[
<b>{html.escape(camera["name"])}</b><br>
Source: OpenWebcamDB<br>
Category: {html.escape(camera.get("category", ""))}<br>
City: {html.escape(camera.get("city", ""))}<br>
County: {html.escape(camera.get("county", ""))}<br>
{f'<a href="{html.escape(camera["url"])}">Open webcam page</a><br>' if camera.get("url") else ""}
{f'<a href="{html.escape(camera["stream_url"])}">Open live stream</a><br>' if camera.get("stream_url") else ""}
{f'<a href="{html.escape(camera["thumbnail"])}">Open preview image</a><br><img src="{html.escape(camera["thumbnail"])}" width="320">' if camera.get("thumbnail") else ""}
<br><a href="https://openwebcamdb.com/">Powered by OpenWebcamDB.com</a>
]]>"""

        ET.SubElement(placemark, "description").text = description

        point = ET.SubElement(placemark, "Point")
        ET.SubElement(point, "coordinates").text = (
            f'{camera["lon"]},{camera["lat"]},0'
        )

    temporary = KML_FILE.with_suffix(".kml.tmp")
    ET.ElementTree(kml).write(
        temporary,
        encoding="utf-8",
        xml_declaration=True,
    )
    temporary.replace(KML_FILE)


def write_network_kml() -> None:
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>OpenWebcamDB California Cameras</name>
    <NetworkLink>
      <name>OpenWebcamDB California Cameras</name>
      <refreshVisibility>1</refreshVisibility>
      <Link>
        <href>{PUBLIC_BASE_URL}/atak/openwebcamdb-cameras.kml</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>3600</refreshInterval>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""

    NETWORK_FILE.write_text(content, encoding="utf-8")


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        cameras = fetch_cameras()
    except Exception as exc:
        print(f"OpenWebcamDB failed: {exc}", file=sys.stderr)
        return 1

    # Protect the last known-good feed from an empty API response.
    if not cameras and JSON_FILE.exists() and KML_FILE.exists():
        print("OpenWebcamDB returned 0; preserving existing files.")
        return 0

    write_json(cameras)
    write_kml(cameras)
    write_network_kml()

    print(f"OpenWebcamDB: {len(cameras)} California cameras")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())