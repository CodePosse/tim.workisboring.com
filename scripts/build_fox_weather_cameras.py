#!/usr/bin/env python3

from __future__ import annotations

import html
import json
import time
from pathlib import Path
import xml.etree.ElementTree as ET


BASE_DIR = Path("/var/www/html")
ATAK_DIR = BASE_DIR / "atak"
DATA_DIR = ATAK_DIR / "data"

OUTPUT_JSON = DATA_DIR / "fox-weather-cameras.json"
OUTPUT_KML = ATAK_DIR / "fox-weather-cameras.kml"
OUTPUT_NETWORK = ATAK_DIR / "fox-weather-network.kml"

PUBLIC_KML_URL = (
    "https://tim.workisboring.com/atak/"
    "fox-weather-cameras.kml"
)


CAMERAS = [
    {
        "id": "fox-weather-catalina-island",
        "name": "Catalina Island – Avalon",
        "source": "FOX 10 / Weather Vision",
        "category": "Live Island Webcam",
        "lat": 33.3428,
        "lon": -118.3282,
        "county": "Los Angeles",
        "heading": "",
        "thumbnail": "",
        "url": "https://www.fox10phoenix.com/webcams-catalina",
        "stream_url": "",
        "stream_type": "external-page",
        "region": "Southern California",
        "attribution": "FOX 10 Phoenix / Weather Vision",
    },
    {
        "id": "fox-weather-lax",
        "name": "Los Angeles – LAX Airport",
        "source": "FOX 10 / Weather Vision",
        "category": "Live Airport Webcam",
        "lat": 33.9416,
        "lon": -118.4085,
        "county": "Los Angeles",
        "heading": "",
        "thumbnail": "",
        "url": "https://www.fox10phoenix.com/webcams-los-angeles",
        "stream_url": "",
        "stream_type": "external-page",
        "region": "Southern California",
        "attribution": "FOX 10 Phoenix / Weather Vision",
    },
    {
        "id": "fox-weather-ontario-airport",
        "name": "Ontario International Airport",
        "source": "FOX 10 / Weather Vision",
        "category": "Live Airport Webcam",
        "lat": 34.0560,
        "lon": -117.6012,
        "county": "San Bernardino",
        "heading": "",
        "thumbnail": "",
        "url": "https://www.fox10phoenix.com/webcams-ontario",
        "stream_url": "",
        "stream_type": "external-page",
        "region": "Southern California",
        "attribution": "FOX 10 Phoenix / Weather Vision",
    },
    {
        "id": "fox-weather-santa-monica",
        "name": "Santa Monica Beach",
        "source": "FOX 10 / Weather Vision",
        "category": "Live Beach Webcam",
        "lat": 34.0094,
        "lon": -118.4973,
        "county": "Los Angeles",
        "heading": "",
        "thumbnail": "",
        "url": (
            "https://www.fox10phoenix.com/"
            "webcams-santa-monica-beach"
        ),
        "stream_url": "",
        "stream_type": "external-page",
        "region": "Southern California",
        "attribution": "FOX 10 Phoenix / Weather Vision",
    },
]


def write_json() -> None:
    payload = {
        "source_key": "fox-weather",
        "title": "FOX / Weather Vision Southern California Cameras",
        "generated_at": int(time.time()),
        "count": len(CAMERAS),
        "cameras": CAMERAS,
    }

    OUTPUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_text(
    parent: ET.Element,
    tag: str,
    value: object,
) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = str(value)
    return element


def write_kml() -> None:
    kml = ET.Element(
        "kml",
        xmlns="http://www.opengis.net/kml/2.2",
    )
    document = ET.SubElement(kml, "Document")

    add_text(
        document,
        "name",
        "FOX / Weather Vision Southern California Cameras",
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

    folder = ET.SubElement(document, "Folder")
    add_text(
        folder,
        "name",
        "FOX / Weather Vision Cameras",
    )

    for camera in CAMERAS:
        placemark = ET.SubElement(folder, "Placemark")
        add_text(placemark, "name", camera["name"])
        add_text(placemark, "styleUrl", "#camera-style")

        safe_url = html.escape(camera["url"], quote=True)
        safe_name = html.escape(camera["name"])

        description = (
            f"<b>{safe_name}</b><br>"
            f"Type: {html.escape(camera['category'])}<br>"
            f"Source: FOX 10 Phoenix / Weather Vision<br>"
            f"County: {html.escape(camera['county'])}<br>"
            f'<a href="{safe_url}">Open live camera page</a><br>'
            "Playback is provided on the official FOX page."
        )

        add_text(placemark, "description", description)

        point = ET.SubElement(placemark, "Point")
        add_text(
            point,
            "coordinates",
            f"{camera['lon']},{camera['lat']},0",
        )

    ET.ElementTree(kml).write(
        OUTPUT_KML,
        encoding="utf-8",
        xml_declaration=True,
    )


def write_network_kml() -> None:
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>FOX / Weather Vision Cameras Auto Refresh</name>
    <NetworkLink>
      <name>FOX / Weather Vision Southern California Cameras</name>
      <refreshVisibility>1</refreshVisibility>
      <Link>
        <href>{PUBLIC_KML_URL}</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>21600</refreshInterval>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""

    OUTPUT_NETWORK.write_text(
        content,
        encoding="utf-8",
    )


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    write_json()
    write_kml()
    write_network_kml()

    print(f"Wrote {OUTPUT_JSON} with {len(CAMERAS)} cameras")
    print(f"Wrote {OUTPUT_KML}")
    print(f"Wrote {OUTPUT_NETWORK}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
