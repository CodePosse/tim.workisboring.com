#!/usr/bin/env python3
"""
Build a standalone Southern California curated webcam KML feed.

Inputs:
    /var/www/html/atak/data/curated-socal-cameras.json

Outputs:
    /var/www/html/atak/curated-socal-cameras.kml
    /var/www/html/atak/curated-socal-network.kml

This script does not modify or replace any existing camera source.
It does not scrape camera pages, call APIs, or download streams.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_INPUT = Path("/var/www/html/atak/data/curated-socal-cameras.json")
DEFAULT_KML = Path("/var/www/html/atak/curated-socal-cameras.kml")
DEFAULT_NETWORK_KML = Path("/var/www/html/atak/curated-socal-network.kml")
DEFAULT_PUBLIC_KML_URL = (
    "https://tim.workisboring.com/atak/curated-socal-cameras.kml"
)
DEFAULT_REFRESH_SECONDS = 900
USER_AGENT = (
    "tim.workisboring.com curated camera validator/1.0 "
    "(https://tim.workisboring.com/atak/cameras.html)"
)


class CatalogError(RuntimeError):
    pass


def load_catalog(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except FileNotFoundError as exc:
        raise CatalogError(f"Catalog not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc

    if not isinstance(catalog, dict):
        raise CatalogError("Catalog root must be a JSON object.")

    cameras = catalog.get("cameras")
    if not isinstance(cameras, list):
        raise CatalogError('Catalog must contain a "cameras" array.')

    return catalog


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def clean_url(value: Any) -> str:
    url = clean_text(value)
    if not url:
        return ""
    if not url.startswith(("https://", "http://")):
        raise CatalogError(f"URL must begin with http:// or https://: {url}")
    return url


def as_float(value: Any, field: str, camera_id: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CatalogError(
            f'Camera "{camera_id}" has invalid {field}: {value!r}'
        ) from exc
    return result


def normalize_camera(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CatalogError(f"Camera entry #{index + 1} must be an object.")

    camera_id = clean_text(raw.get("id"))
    name = clean_text(raw.get("name"))

    if not camera_id:
        raise CatalogError(f"Camera entry #{index + 1} is missing id.")
    if not name:
        raise CatalogError(f'Camera "{camera_id}" is missing name.')

    latitude = as_float(raw.get("latitude"), "latitude", camera_id)
    longitude = as_float(raw.get("longitude"), "longitude", camera_id)

    if not -90 <= latitude <= 90:
        raise CatalogError(f'Camera "{camera_id}" latitude is out of range.')
    if not -180 <= longitude <= 180:
        raise CatalogError(f'Camera "{camera_id}" longitude is out of range.')

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise CatalogError(f'Camera "{camera_id}" enabled must be true or false.')

    camera = {
        "id": camera_id,
        "name": name,
        "enabled": enabled,
        "category": clean_text(raw.get("category")) or "Other",
        "latitude": latitude,
        "longitude": longitude,
        "city": clean_text(raw.get("city")),
        "county": clean_text(raw.get("county")),
        "operator": clean_text(raw.get("operator")),
        "description": clean_text(raw.get("description")),
        "pageUrl": clean_url(raw.get("pageUrl")),
        "imageUrl": clean_url(raw.get("imageUrl")),
        "streamUrl": clean_url(raw.get("streamUrl")),
        "youtubeUrl": clean_url(raw.get("youtubeUrl")),
        "channelUrl": clean_url(raw.get("channelUrl")),
        "sourceType": clean_text(raw.get("sourceType")) or "webcam",
        "priority": int(raw.get("priority", 50)),
        "featured": bool(raw.get("featured", False)),
        "tags": [
            clean_text(tag)
            for tag in raw.get("tags", [])
            if clean_text(tag)
        ] if isinstance(raw.get("tags", []), list) else [],
        "notes": clean_text(raw.get("notes")),
    }

    if not any(
        camera[field]
        for field in (
            "pageUrl", "imageUrl", "streamUrl",
            "youtubeUrl", "channelUrl"
        )
    ):
        raise CatalogError(
            f'Camera "{camera_id}" must have at least one page, image, stream, YouTube, or channel URL.'
        )

    return camera


def normalize_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(catalog["cameras"]):
        camera = normalize_camera(raw, index)

        if camera["id"] in seen_ids:
            raise CatalogError(f'Duplicate camera id: {camera["id"]}')

        seen_ids.add(camera["id"])

        if camera["enabled"]:
            normalized.append(camera)

    normalized.sort(
        key=lambda camera: (
            not camera["featured"],
            -camera["priority"],
            camera["category"].casefold(),
            camera["county"].casefold(),
            camera["city"].casefold(),
            camera["name"].casefold(),
        )
    )
    return normalized


def cdata(value: str) -> str:
    return value.replace("]]>", "]]]]><![CDATA[>")


def link(label: str, url: str) -> str:
    if not url:
        return ""
    return (
        f'<a href="{html.escape(url, quote=True)}">'
        f"{html.escape(label)}</a>"
    )


def description_html(camera: dict[str, Any]) -> str:
    lines = [
        f"<b>{html.escape(camera['name'])}</b>",
        f"Category: {html.escape(camera['category'])}",
    ]

    if camera["city"]:
        lines.append(f"City: {html.escape(camera['city'])}")
    if camera["county"]:
        lines.append(f"County: {html.escape(camera['county'])}")
    if camera["operator"]:
        lines.append(f"Operator: {html.escape(camera['operator'])}")
    if camera["description"]:
        lines.append(html.escape(camera["description"]))

    links = [
        link("Camera Page", camera["pageUrl"]),
        link("Latest Image", camera["imageUrl"]),
        link("Open Stream", camera["streamUrl"]),
        link("Watch YouTube Video", camera["youtubeUrl"]),
        link("Open YouTube Streams", camera["channelUrl"]),
    ]
    lines.extend(item for item in links if item)

    if camera["sourceType"]:
        lines.append(f"Type: {html.escape(camera['sourceType'])}")
    if camera["tags"]:
        lines.append(f"Tags: {html.escape(', '.join(camera['tags']))}")
    if camera["notes"]:
        lines.append(f"Notes: {html.escape(camera['notes'])}")

    return "<br>\n".join(lines)


def build_kml(cameras: list[dict[str, Any]], document_name: str) -> str:
    generated = datetime.now(timezone.utc).isoformat()
    categories: dict[str, list[dict[str, Any]]] = {}

    for camera in cameras:
        categories.setdefault(camera["category"], []).append(camera)

    folders: list[str] = []

    for category, category_cameras in sorted(
        categories.items(), key=lambda item: item[0].casefold()
    ):
        placemarks: list[str] = []

        for camera in category_cameras:
            description = cdata(description_html(camera))
            placemarks.append(
                f"""      <Placemark>
        <name>{html.escape(camera['name'])}</name>
        <description><![CDATA[{description}]]></description>
        <styleUrl>#camera</styleUrl>
        <ExtendedData>
          <Data name="id"><value>{html.escape(camera['id'])}</value></Data>
          <Data name="category"><value>{html.escape(camera['category'])}</value></Data>
          <Data name="operator"><value>{html.escape(camera['operator'])}</value></Data>
          <Data name="source"><value>Curated Southern California Cameras</value></Data>
        </ExtendedData>
        <Point>
          <coordinates>{camera['longitude']:.6f},{camera['latitude']:.6f},0</coordinates>
        </Point>
      </Placemark>"""
            )

        folders.append(
            f"""    <Folder>
      <name>{html.escape(category)}</name>
{os.linesep.join(placemarks)}
    </Folder>"""
        )

    folder_text = os.linesep.join(folders)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{html.escape(document_name)}</name>
    <description>Generated {html.escape(generated)}; {len(cameras)} enabled cameras</description>
    <Style id="camera">
      <IconStyle>
        <scale>1.0</scale>
        <Icon>
          <href>https://maps.google.com/mapfiles/kml/shapes/camera.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle>
        <scale>0.8</scale>
      </LabelStyle>
    </Style>
{folder_text}
  </Document>
</kml>
"""


def build_network_kml(
    public_kml_url: str,
    refresh_seconds: int,
    document_name: str,
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{html.escape(document_name)} Auto Refresh</name>
    <NetworkLink>
      <name>{html.escape(document_name)}</name>
      <refreshVisibility>1</refreshVisibility>
      <Link>
        <href>{html.escape(public_kml_url)}</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>{refresh_seconds}</refreshInterval>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def check_url(url: str, timeout: int = 15) -> tuple[bool, str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,image/*,*/*;q=0.8",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            return 200 <= status < 400, f"HTTP {status}"
    except HTTPError as exc:
        # 401/403 may indicate a working page that blocks automated checks.
        if exc.code in (401, 403):
            return True, f"HTTP {exc.code} (automation blocked)"
        return False, f"HTTP {exc.code}"
    except URLError as exc:
        return False, f"network error: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def validate_urls(cameras: list[dict[str, Any]]) -> bool:
    all_ok = True

    for camera in cameras:
        urls = [
            ("page", camera["pageUrl"]),
            ("image", camera["imageUrl"]),
            ("stream", camera["streamUrl"]),
            ("youtube", camera["youtubeUrl"]),
            ("channel", camera["channelUrl"]),
        ]

        for url_type, url in urls:
            if not url:
                continue

            ok, message = check_url(url)
            state = "OK" if ok else "FAIL"
            print(f"[{state}] {camera['id']} {url_type}: {message} — {url}")

            if not ok:
                all_ok = False

    return all_ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build curated Southern California webcam KML files."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-kml", type=Path, default=DEFAULT_KML)
    parser.add_argument(
        "--output-network-kml",
        type=Path,
        default=DEFAULT_NETWORK_KML,
    )
    parser.add_argument(
        "--public-kml-url",
        default=DEFAULT_PUBLIC_KML_URL,
    )
    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=DEFAULT_REFRESH_SECONDS,
    )
    parser.add_argument(
        "--check-urls",
        action="store_true",
        help="Check catalog URLs before writing KML.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate JSON and URLs without writing KML.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        catalog = load_catalog(args.input)
        cameras = normalize_catalog(catalog)

        if not cameras:
            raise CatalogError("No enabled cameras found.")

        print(f"Loaded {len(cameras)} enabled cameras from {args.input}")

        if args.check_urls or args.check_only:
            urls_ok = validate_urls(cameras)
            if not urls_ok:
                print(
                    "One or more URLs failed validation. "
                    "Existing KML files were not changed.",
                    file=sys.stderr,
                )
                return 2

        if args.check_only:
            print("Catalog and URLs are valid.")
            return 0

        document_name = clean_text(
            catalog.get("name")
        ) or "Southern California Curated Cameras"

        kml = build_kml(cameras, document_name)
        network_kml = build_network_kml(
            args.public_kml_url,
            max(60, args.refresh_seconds),
            document_name,
        )

        write_atomic(args.output_kml, kml)
        write_atomic(args.output_network_kml, network_kml)

        print(f"Wrote {args.output_kml}")
        print(f"Wrote {args.output_network_kml}")
        return 0

    except CatalogError as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        print("Existing KML files were not changed.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected build failure: {exc}", file=sys.stderr)
        print("Existing KML files were not changed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
