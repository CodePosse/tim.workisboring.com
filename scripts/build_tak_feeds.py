#!/usr/bin/env python3
import html
import json
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

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
FAA_SITES_API = "https://api.weathercams.faa.gov/sites"

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
    "caloes-weather": {
        "title": "Cal OES Weather Cameras",
        "json": "caloes-weather-cameras.json",
        "kml": "caloes-weather-cameras.kml",
        "network": "caloes-weather-network.kml",
    },
    "caloes-coastal": {
        "title": "Cal OES Coastal / Harbor Cameras",
        "json": "caloes-coastal-cameras.json",
        "kml": "caloes-coastal-cameras.kml",
        "network": "caloes-coastal-network.kml",
    },
    "caloes-other": {
        "title": "Cal OES Other Cameras",
        "json": "caloes-other-cameras.json",
        "kml": "caloes-other-cameras.kml",
        "network": "caloes-other-network.kml",
    },
    "usgs": {
        "title": "USGS River / Water Cameras",
        "json": "usgs-cameras.json",
        "kml": "usgs-cameras.kml",
        "network": "usgs-network.kml",
    },
    "faa": {
        "title": "FAA Weather Cameras",
        "json": "faa-weathercams.json",
        "kml": "faa-weathercams.kml",
        "network": "faa-weathercams-network.kml",
    },
}


def pick(obj, keys, default=""):
    for key in keys:
        value = obj.get(key)
        if value not in (None, "", []):
            return value
    return default


def in_california_bbox(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False

    return (
        SOCAL_BBOX["ymin"] <= lat <= 42.1 and
        -124.6 <= lon <= SOCAL_BBOX["xmax"]
    )


def in_socal_bbox(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False

    return (
        SOCAL_BBOX["ymin"] <= lat <= SOCAL_BBOX["ymax"] and
        SOCAL_BBOX["xmin"] <= lon <= SOCAL_BBOX["xmax"]
    )


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
    (DATA_DIR / info["json"]).write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
        ET.SubElement(placemark, "name").text = str(cam["name"])
        ET.SubElement(placemark, "styleUrl").text = "#camera-style"

        desc = f"""<![CDATA[
<b>{html.escape(str(cam["name"]))}</b><br>
Type: {html.escape(str(cam.get("category", "")))}<br>
Source: {html.escape(str(cam.get("source", "")))}<br>
County: {html.escape(str(cam.get("county", "")))}<br>
{f'View: {html.escape(str(cam.get("heading")))}°<br>' if cam.get("heading") else ""}
{f'<a href="{html.escape(str(cam.get("url")))}">Open Camera</a><br>' if cam.get("url") else ""}
{f'<a href="{html.escape(str(cam.get("thumbnail")))}">Open Latest Image</a><br><img src="{html.escape(str(cam.get("thumbnail")))}" width="320">' if cam.get("thumbnail") else ""}
]]>"""

        ET.SubElement(placemark, "description").text = desc
        point = ET.SubElement(placemark, "Point")
        ET.SubElement(point, "coordinates").text = f'{cam["lon"]},{cam["lat"]},0'

    ET.ElementTree(kml).write(OUT_DIR / info["kml"], encoding="utf-8", xml_declaration=True)


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
    write_json(source_key, cameras)
    make_kml(source_key, cameras)
    make_network_kml(source_key)
    print(f"{source_key}: {len(cameras)}")


def fetch_alertwest():
    cameras = []
    r = requests.get(ALERTWEST_API, timeout=30)
    r.raise_for_status()

    for cam in r.json():
        site = cam.get("site") or {}
        image = cam.get("image") or {}
        pos = cam.get("position") or {}

        lat = site.get("latitude")
        lon = site.get("longitude")

        if lat is None or lon is None:
            continue

        cameras.append({
            "id": f'alertwest-{cam.get("id") or cam.get("name")}',
            "name": cam.get("name") or "ALERTCalifornia Camera",
            "source": "ALERTCalifornia / AlertWest",
            "category": "🔥 Fire Camera",
            "lat": lat,
            "lon": lon,
            "county": site.get("county") or "",
            "heading": pos.get("pan") or "",
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
    ]).lower()

    if "alert" in raw or "fire" in raw:
        return "caloes-fire", "🔥 Fire Camera"
    if "traffic" in raw or "caltrans" in raw or "road" in raw or "highway" in raw:
        return "caloes-traffic", "🚗 Traffic Camera"
    if "weather" in raw or "wx" in raw:
        return "caloes-weather", "🌦 Weather Camera"
    if "harbor" in raw or "coast" in raw or "tsunami" in raw or "beach" in raw or "pier" in raw:
        return "caloes-coastal", "🌊 Coastal / Harbor Camera"

    return "caloes-other", "📷 Webcam"


def fetch_caloes_split():
    buckets = {
        "caloes-fire": [],
        "caloes-traffic": [],
        "caloes-weather": [],
        "caloes-coastal": [],
        "caloes-other": [],
    }

    r = requests.get(CALOES_API, params=arcgis_params(), timeout=30)
    r.raise_for_status()

    for feature in r.json().get("features", []):
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}

        lat = geom.get("y")
        lon = geom.get("x")
        if lat is None or lon is None:
            continue

        key, category = classify_caloes(attrs)
        if key == "🌦 Weather Camera":
            key = "caloes-weather"

        buckets[key].append({
            "id": f'caloes-{pick(attrs, ["OBJECTID", "GlobalID"], lat)}',
            "name": pick(attrs, ["Location", "Name", "NAME"], "Cal OES Webcam"),
            "source": pick(attrs, ["Source"], "Cal OES"),
            "category": category,
            "lat": lat,
            "lon": lon,
            "county": str(pick(attrs, ["County"], "")).title(),
            "heading": pick(attrs, ["View_Degrees"], ""),
            "thumbnail": pick(attrs, ["Thumbnail_Url"], ""),
            "url": pick(attrs, ["Webcam_URL", "Consolidated_URL", "Source_URL"], ""),
        })

    return buckets


def fetch_usgs():
    cameras = []
    r = requests.get(USGS_NIMS_CAMERAS, timeout=30)
    r.raise_for_status()

    data = r.json()
    if isinstance(data, dict):
        data = data.get("cameras", data.get("items", data.get("data", [])))

    for cam in data:
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
            "county": pick(cam, ["county", "countyName"], ""),
            "heading": "",
            "thumbnail": thumbnail or image_url,
            "url": image_url or timelapse,
            "timelapse": timelapse,
        })

    return cameras


def fetch_faa():
    cameras = []

    try:
        r = requests.get(
            FAA_SITES_API,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        r.raise_for_status()
    except Exception as exc:
        print(f"faa failed: {exc}")
        return cameras

    data = r.json()
    sites = data.get("payload", data if isinstance(data, list) else [])

    for site in sites:
        lat = pick(site, ["latitude", "lat"])
        lon = pick(site, ["longitude", "lon"])

        state = str(pick(site, ["state", "stateCode", "province"], "")).upper()
        if state and state not in ("CA", "CALIFORNIA"):
            continue

        if not in_california_bbox(lat, lon):
            continue

        site_id = pick(site, ["siteId", "id"])
        site_name = pick(site, ["siteName", "name"], "FAA WeatherCam")
        icao = pick(site, ["icao", "siteIdentifier", "identifier"], "")

        url = f"https://weathercams.faa.gov/cameras/cameraSite/{site_id}/details/weather" if site_id else "https://weathercams.faa.gov/"

        cameras.append({
            "id": f"faa-{site_id or icao or site_name}",
            "name": f"{site_name} {f'({icao})' if icao else ''}".strip(),
            "source": "FAA WeatherCams",
            "category": "✈️ Aviation Weather Camera",
            "lat": float(lat),
            "lon": float(lon),
            "county": "",
            "heading": "",
            "thumbnail": "",
            "url": url,
        })

    return cameras


def main():
    alertwest = fetch_alertwest()
    write_outputs("alertwest", alertwest)

    caloes = fetch_caloes_split()
    for key, cameras in caloes.items():
        write_outputs(key, cameras)

    try:
        usgs = fetch_usgs()
        write_outputs("usgs", usgs)
    except Exception as exc:
        print(f"usgs failed: {exc}")
        write_outputs("usgs", [])

    faa = fetch_faa()
    write_outputs("faa", faa)


if __name__ == "__main__":
    main()