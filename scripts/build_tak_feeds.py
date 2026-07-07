#!/usr/bin/env python3
import html
import json
import os
import time
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

BASE_URL = "https://tim.workisboring.com"

OUT_DIR = Path("/var/www/html/atak")
DATA_DIR = OUT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SOCAL_BBOX = {
    "xmin": -121.0,
    "ymin": 32.3,
    "xmax": -114.0,
    "ymax": 36.8,
    "spatialReference": {"wkid": 4326},
}

ALERTWEST_API = "https://api.cdn.prod.alertwest.com/api/firecams/v0/cameras"
CALOES_API = "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/CalOES_California_Webcams/FeatureServer/0/query"
USGS_NIMS_CAMERAS = "https://api.waterdata.usgs.gov/nims/v0/cameras"

WINDY_API_KEY = os.environ.get("WINDY_API_KEY", "")
WINDY_API = "https://api.windy.com/webcams/api/v3/webcams"

WINDY_REGIONS = [
    ("Los Angeles", 34.0522, -118.2437),
    ("Orange County", 33.7175, -117.8311),
    ("San Diego", 32.7157, -117.1611),
    ("Ventura", 34.2805, -119.2945),
    ("Santa Barbara", 34.4208, -119.6982),
    ("Palm Springs", 33.8303, -116.5453),
    ("Big Bear", 34.2439, -116.9114),
]

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
        "title": "USGS River / Water Cameras",
        "json": "usgs-cameras.json",
        "kml": "usgs-cameras.kml",
        "network": "usgs-network.kml",
    },
    "windy": {
        "title": "Windy Southern California Webcams",
        "json": "windy-webcams.json",
        "kml": "windy-webcams.kml",
        "network": "windy-webcams-network.kml",
    },
}


def pick(obj, keys, default=""):
    if not isinstance(obj, dict):
        return default

    for key in keys:
        value = obj.get(key)
        if value not in (None, "", []):
            return value

    return default


def in_socal_bbox(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False

    return (
        SOCAL_BBOX["ymin"] <= lat <= SOCAL_BBOX["ymax"]
        and SOCAL_BBOX["xmin"] <= lon <= SOCAL_BBOX["xmax"]
    )


def in_california_bbox(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False

    return 32.3 <= lat <= 42.1 and -124.6 <= lon <= -114.0


def arcgis_params():
    return {
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "geometry": json.dumps(SOCAL_BBOX),
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "resultRecordCount": 3000,
    }


def write_json(source_key, cameras):
    info = SOURCES[source_key]

    payload = {
        "source_key": source_key,
        "title": info["title"],
        "generated_at": int(time.time()),
        "count": len(cameras),
        "cameras": cameras,
    }

    (DATA_DIR / info["json"]).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def make_kml(source_key, cameras):
    info = SOURCES[source_key]

    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = info["title"]

    style = ET.SubElement(doc, "Style", id="camera-style")
    icon_style = ET.SubElement(style, "IconStyle")
    ET.SubElement(icon_style, "scale").text = "1.1"
    icon = ET.SubElement(icon_style, "Icon")
    ET.SubElement(icon, "href").text = "https://maps.google.com/mapfiles/kml/shapes/camera.png"

    folder = ET.SubElement(doc, "Folder")
    ET.SubElement(folder, "name").text = info["title"]

    for cam in cameras:
        placemark = ET.SubElement(folder, "Placemark")
        ET.SubElement(placemark, "name").text = str(cam.get("name", "Camera"))
        ET.SubElement(placemark, "styleUrl").text = "#camera-style"

        desc = f"""<![CDATA[
<b>{html.escape(str(cam.get("name", "Camera")))}</b><br>
Type: {html.escape(str(cam.get("category", "")))}<br>
Source: {html.escape(str(cam.get("source", "")))}<br>
County: {html.escape(str(cam.get("county", "")))}<br>
{f'View: {html.escape(str(cam.get("heading")))}°<br>' if cam.get("heading") else ""}
{f'Region: {html.escape(str(cam.get("region")))}<br>' if cam.get("region") else ""}
{f'<a href="{html.escape(str(cam.get("url")))}">Open Camera</a><br>' if cam.get("url") else ""}
{f'<a href="{html.escape(str(cam.get("timelapse")))}">Open Timelapse</a><br>' if cam.get("timelapse") else ""}
{f'<a href="{html.escape(str(cam.get("thumbnail")))}">Open Latest Image</a><br><img src="{html.escape(str(cam.get("thumbnail")))}" width="320">' if cam.get("thumbnail") else ""}
]]>"""

        ET.SubElement(placemark, "description").text = desc

        point = ET.SubElement(placemark, "Point")
        ET.SubElement(point, "coordinates").text = f'{cam["lon"]},{cam["lat"]},0'

    ET.ElementTree(kml).write(
        OUT_DIR / info["kml"],
        encoding="utf-8",
        xml_declaration=True,
    )


def make_network_kml(source_key):
    info = SOURCES[source_key]
    href = f"{BASE_URL}/atak/{info['kml']}"

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{html.escape(info["title"])} Auto Refresh</name>
    <NetworkLink>
      <name>{html.escape(info["title"])}</name>
      <refreshVisibility>1</refreshVisibility>
      <Link>
        <href>{href}</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>900</refreshInterval>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""

    (OUT_DIR / info["network"]).write_text(content, encoding="utf-8")


def write_outputs(source_key, cameras):
    # Do not overwrite Windy with an empty response.
    # Windy can intermittently return 0 for nearby queries.
    if source_key == "windy" and len(cameras) == 0:
        existing_json = DATA_DIR / SOURCES[source_key]["json"]
        existing_kml = OUT_DIR / SOURCES[source_key]["kml"]

        if existing_json.exists() and existing_kml.exists():
            print("windy: 0 returned, keeping previous cached feed")
            make_network_kml(source_key)
            return

    write_json(source_key, cameras)
    make_kml(source_key, cameras)
    make_network_kml(source_key)
    print(f"{source_key}: {len(cameras)}")


def fetch_alertwest():
    cameras = []

    response = requests.get(ALERTWEST_API, timeout=30)
    response.raise_for_status()

    for cam in response.json():
        site = cam.get("site") or {}
        image = cam.get("image") or {}
        position = cam.get("position") or {}

        lat = site.get("latitude")
        lon = site.get("longitude")

        if lat is None or lon is None:
            continue

        cameras.append({
            "id": f'alertwest-{cam.get("id") or cam.get("name")}',
            "name": cam.get("name") or "ALERTCalifornia Camera",
            "source": "ALERTCalifornia / AlertWest",
            "category": "🔥 Fire Camera",
            "lat": float(lat),
            "lon": float(lon),
            "county": site.get("county") or "",
            "heading": position.get("pan") or "",
            "thumbnail": image.get("url") or "",
            "url": image.get("url") or "https://alertcalifornia.org/",
        })

    return cameras


def classify_caloes(attrs):
    raw = " ".join([
        str(pick(attrs, ["CameraType"], "")),
        str(pick(attrs, ["Display_Type"], "")),
        str(pick(attrs, ["Source"], "")),
        str(pick(attrs, ["Location"], "")),
        str(pick(attrs, ["Webcam_URL"], "")),
        str(pick(attrs, ["Consolidated_URL"], "")),
    ]).lower()

    if "alert" in raw or "fire" in raw:
        return "caloes-fire", "🔥 Fire Camera"

    if "traffic" in raw or "caltrans" in raw or "road" in raw or "highway" in raw:
        return "caloes-traffic", "🚗 Traffic Camera"

    return None, None


def fetch_caloes_split():
    buckets = {
        "caloes-fire": [],
        "caloes-traffic": [],
    }

    response = requests.get(CALOES_API, params=arcgis_params(), timeout=30)
    response.raise_for_status()

    for feature in response.json().get("features", []):
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}

        lat = geom.get("y")
        lon = geom.get("x")

        if lat is None or lon is None:
            continue

        key, category = classify_caloes(attrs)

        if not key:
            continue

        buckets[key].append({
            "id": f'caloes-{pick(attrs, ["OBJECTID", "GlobalID"], lat)}',
            "name": pick(attrs, ["Location", "Name", "NAME"], "Cal OES Webcam"),
            "source": pick(attrs, ["Source"], "Cal OES"),
            "category": category,
            "lat": float(lat),
            "lon": float(lon),
            "county": str(pick(attrs, ["County"], "")).title(),
            "heading": pick(attrs, ["View_Degrees"], ""),
            "thumbnail": pick(attrs, ["Thumbnail_Url"], ""),
            "url": pick(attrs, ["Webcam_URL", "Consolidated_URL", "Source_URL"], ""),
        })

    return buckets


def fetch_usgs():
    cameras = []

    response = requests.get(USGS_NIMS_CAMERAS, timeout=30)
    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        data = data.get("cameras", data.get("items", data.get("data", [])))

    for cam in data:
        if cam.get("hideCam"):
            continue

        cam_id = pick(cam, ["camId", "cameraId", "id"])
        name = pick(cam, ["camName", "cameraName", "name"], "USGS Camera")

        lat = pick(cam, ["lat", "latitude"])
        lon = pick(cam, ["lng", "lon", "longitude"])
        state = str(pick(cam, ["stateAbrv", "state", "stateCode"], "")).upper()

        if state and state not in ("CA", "CALIFORNIA"):
            continue

        if not in_california_bbox(lat, lon):
            continue

        thumb_dir = pick(cam, ["thumbDir"], "")
        small_dir = pick(cam, ["smallDir"], "")
        overlay_dir = pick(cam, ["overlayDir"], "")
        tl_dir = pick(cam, ["tlDir"], "")

        thumbnail = f"{thumb_dir}{cam_id}_newest.jpg" if thumb_dir and cam_id else ""
        image_url = f"{small_dir or overlay_dir}{cam_id}_newest.jpg" if (small_dir or overlay_dir) and cam_id else ""
        timelapse = f"{tl_dir}{cam_id}.mp4" if tl_dir and cam_id else ""

        cameras.append({
            "id": f"usgs-{cam_id}",
            "name": name,
            "source": "USGS NIMS",
            "category": "🌊 River / Water Camera",
            "lat": float(lat),
            "lon": float(lon),
            "county": "",
            "heading": "",
            "thumbnail": thumbnail or image_url,
            "url": image_url or timelapse,
            "timelapse": timelapse,
        })

    return cameras


def first_url(value):
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ["url", "preview", "thumbnail", "full", "day", "month", "lifetime"]:
            if value.get(key):
                return value[key]

    return ""


def fetch_windy():
    cameras = {}

    if not WINDY_API_KEY:
        print("windy skipped: WINDY_API_KEY not set")
        return []

    headers = {
        "x-windy-api-key": WINDY_API_KEY,
        "Accept": "application/json",
        "User-Agent": "SoCal-TAK/0.1",
    }

    for region_name, lat, lon in WINDY_REGIONS:
        params = {
            "limit": 50,
            "nearby": f"{lat},{lon},250",
            "include": "images,location,player,urls,categories",
        }

        try:
            response = requests.get(
                WINDY_API,
                headers=headers,
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(f"windy {region_name} failed: {exc}")
            continue

        for cam in data.get("webcams", []):
            cam_id = str(pick(cam, ["webcamId", "id"], ""))

            if not cam_id:
                continue

            location = cam.get("location") or {}
            images = cam.get("images") or {}
            urls = cam.get("urls") or {}
            player = cam.get("player") or {}

            cam_lat = pick(location, ["latitude", "lat"])
            cam_lon = pick(location, ["longitude", "lon", "lng"])

            if not in_california_bbox(cam_lat, cam_lon):
                continue

            title = pick(cam, ["title", "name"], "Windy Webcam")

            thumbnail = ""
            image_url = ""

            if isinstance(images, dict):
                current = images.get("current") or {}
                if isinstance(current, dict):
                    thumbnail = first_url(current.get("thumbnail")) or first_url(current.get("preview"))
                    image_url = first_url(current.get("full")) or first_url(current.get("preview")) or thumbnail

            url = (
                first_url(urls.get("detail")) if isinstance(urls, dict) else ""
            ) or (
                first_url(urls.get("web")) if isinstance(urls, dict) else ""
            ) or (
                first_url(player.get("day")) if isinstance(player, dict) else ""
            ) or image_url or "https://www.windy.com/webcams"

            cameras[cam_id] = {
                "id": f"windy-{cam_id}",
                "name": title,
                "source": "Windy Webcams",
                "category": "🌎 Public Webcam",
                "lat": float(cam_lat),
                "lon": float(cam_lon),
                "county": "",
                "heading": "",
                "thumbnail": thumbnail or image_url,
                "url": url,
                "region": region_name,
            }

    return list(cameras.values())


def main():
    try:
        write_outputs("alertwest", fetch_alertwest())
    except Exception as exc:
        print(f"alertwest failed: {exc}")
        write_outputs("alertwest", [])

    try:
        caloes = fetch_caloes_split()
        write_outputs("caloes-fire", caloes["caloes-fire"])
        write_outputs("caloes-traffic", caloes["caloes-traffic"])
    except Exception as exc:
        print(f"caloes failed: {exc}")
        write_outputs("caloes-fire", [])
        write_outputs("caloes-traffic", [])

    try:
        write_outputs("usgs", fetch_usgs())
    except Exception as exc:
        print(f"usgs failed: {exc}")
        write_outputs("usgs", [])

    try:
        write_outputs("windy", fetch_windy())
    except Exception as exc:
        print(f"windy failed: {exc}")
        write_outputs("windy", [])


if __name__ == "__main__":
    main()