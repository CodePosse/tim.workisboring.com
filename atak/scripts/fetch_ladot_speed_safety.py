#!/usr/bin/env python3

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path


SOURCE_URL = (
    "https://services.arcgis.com/G3nmNsarwQblLhip/"
    "arcgis/rest/services/"
    "ApprovedLocations_04012026_view/"
    "FeatureServer/0/query"
)

OUTPUT_FILE = Path("atak/data/ladot-speed-safety.geojson")

EXPECTED_COUNT = 125


def main():
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "orderByFields": "OBJECTID",
        "f": "geojson",
    }

    url = SOURCE_URL + "?" + urllib.parse.urlencode(params)

    print("Fetching LADOT Speed Safety System data...")
    print(SOURCE_URL)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "tim.workisboring.com camera-map updater"
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except Exception as exc:
        print(f"ERROR: Could not download LADOT data: {exc}")
        return 1

    if data.get("type") != "FeatureCollection":
        print("ERROR: LADOT response is not a GeoJSON FeatureCollection.")
        return 1

    features = data.get("features", [])
    count = len(features)

    print(f"Received {count} features.")

    if count != EXPECTED_COUNT:
        print(
            f"WARNING: Expected {EXPECTED_COUNT} features "
            f"but LADOT returned {count}."
        )

    # Make sure every feature has the fields our project expects.
    required_fields = (
        "OBJECTID",
        "DISTRICT",
        "StreetName",
        "XStreet1",
        "XStreet2",
        "speed_limi",
    )

    for feature in features:
        properties = feature.get("properties", {})

        missing = [
            field
            for field in required_fields
            if field not in properties
        ]

        if missing:
            print(
                "ERROR: Feature "
                f"{properties.get('OBJECTID', '?')} "
                f"is missing fields: {', '.join(missing)}"
            )
            return 1

        geometry = feature.get("geometry", {})

        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            print(
                "ERROR: Feature "
                f"{properties.get('OBJECTID', '?')} "
                f"has unexpected geometry: "
                f"{geometry.get('type')}"
            )
            return 1

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )
        f.write("\n")

    print(f"Wrote {OUTPUT_FILE}")
    print("Validation successful.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
