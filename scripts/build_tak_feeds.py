#!/usr/bin/env python3
import html
import json
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

OUT_DIR = Path("/var/www/html/atak")
DATA_DIR = OUT_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

CAMERAS_JSON = DATA_DIR / "cameras.json"
ALL_KML = OUT_DIR / "all-cameras.kml"
NETWORK_KML = OUT_DIR / "all-cameras-network.kml"

SOCAL_BBOX = {
    "xmin": -121.0,
    "ymin": 32.3,
    "xmax": -114.0,
    "ymax": 36.8,
    "spatialReference": {"wkid": 4326},
}

ALERTWEST_API = "https://api.cdn.prod.alertwest.com/api/firecams/v0/cameras"

CALOES_API = "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/CalOES_California_Webcams/FeatureServer/0/query"

CALTRANS_API = "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/CCTV/FeatureServer/0/query"


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


def pick(obj, keys, default=""):
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    return default


def fetch_alertwest():
    items = []
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

        items.append({
            "id": f'alertwest-{cam.get("id") or cam.get("name")}',
            "name": cam.get("name") or "ALERTCalifornia Camera",
            "source": "ALERTCalifornia / AlertWest",
            "category": "Fire Camera",
            "lat": lat,
            "lon": lon,
            "county": site.get("county") or "",
            "heading": pos.get("pan") or "",
            "thumbnail": image.get("url") or "",
            "url": image.get("url") or "https://alertcalifornia.org/",
        })

    return items


def fetch_caloes():
    items = []
    r = requests.get(CALOES_API, params=arcgis_params(), timeout=30)
    r.raise_for_status()
    data = r.json()

    for feature in data.get("features", []):
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}

        lat = geom.get("y")
        lon = geom.get("x")

        if lat is None or lon is None:
            continue

        items.append({
            "id": f'caloes-{pick(attrs, ["OBJECTID", "GlobalID"], lat)}',
            "name": pick(attrs, ["Location", "Name", "NAME"], "Cal OES Webcam"),
            "source": pick(attrs, ["Source"], "Cal OES"),
            "category": str(pick(attrs, ["CameraType", "Display_Type"], "Webcam")).strip(),
            "lat": lat,
            "lon": lon,
            "county": pick(attrs, ["County"], ""),
            "heading": pick(attrs, ["View_Degrees"], ""),
            "thumbnail": pick(attrs, ["Thumbnail_Url"], ""),
            "url": pick(attrs, ["Webcam_URL", "Consolidated_URL", "Source_URL"], ""),
        })

    return items


def fetch_caltrans():
    items = []
    r = requests.get(CALTRANS_API, params=arcgis_params(), timeout=30)
    r.raise_for_status()
    data = r.json()

    for feature in data.get("features", []):
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}

        lat = geom.get("y")
        lon = geom.get("x")

        if lat is None or lon is None:
            continue

        name = pick(attrs, ["locationName", "LOCATIONNAME", "name", "Name"], "Caltrans CCTV")
        district = pick(attrs, ["district", "District", "DISTRICT"], "")
        route = pick(attrs, ["route", "Route", "ROUTE"], "")
        camera_url = pick(attrs, ["cctvUrl", "CCTVURL", "url", "URL", "imageUrl", "IMAGEURL"], "")

        items.append({
            "id": f'caltrans-{pick(attrs, ["OBJECTID", "objectid"], name)}',
            "name": name,
            "source": "Caltrans CCTV",
            "category": "Traffic Camera",
            "lat": lat,
            "lon": lon,
            "county": "",
            "heading": "",
            "thumbnail": camera_url,
            "url": camera_url or "https://quickmap.dot.ca.gov/",
            "district": district,
            "route": route,
        })

    return items


def make_kml(cameras):
    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = "SoCal TAK Public Cameras"

    style = ET.SubElement(doc, "Style", id="camera-style")
    icon_style = ET.SubElement(style, "IconStyle")
    ET.SubElement(icon_style, "scale").text = "1.1"
    icon = ET.SubElement(icon_style, "Icon")
    ET.SubElement(icon, "href").text = "https://maps.google.com/mapfiles/kml/shapes/camera.png"

    folder = ET.SubElement(doc, "Folder")
    ET.SubElement(folder, "name").text = "Public Cameras"

    for cam in cameras:
        placemark = ET.SubElement(folder, "Placemark")
        ET.SubElement(placemark, "name").text = cam["name"]
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

    ET.ElementTree(kml).write(ALL_KML, encoding="utf-8", xml_declaration=True)


def make_network_kml():
    content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>SoCal TAK Public Cameras Auto Refresh</name>
    <NetworkLink>
      <name>SoCal TAK Public Cameras</name>
      <refreshVisibility>1</refreshVisibility>
      <Link>
        <href>https://tim.workisboring.com/atak/all-cameras.kml</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>900</refreshInterval>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""
    NETWORK_KML.write_text(content, encoding="utf-8")


def main():
    cameras = []

    for label, func in [
        ("AlertWest", fetch_alertwest),
        ("Cal OES", fetch_caloes),
        ("Caltrans", fetch_caltrans),
    ]:
        try:
            result = func()
            print(f"{label}: {len(result)} cameras")
            cameras.extend(result)
        except Exception as e:
            print(f"{label} failed: {e}")

    payload = {
        "generated_at": int(time.time()),
        "count": len(cameras),
        "cameras": cameras,
    }

    CAMERAS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    make_kml(cameras)
    make_network_kml()

    print(f"Wrote {CAMERAS_JSON} with {len(cameras)} cameras")
    print(f"Wrote {ALL_KML}")
    print(f"Wrote {NETWORK_KML}")


if __name__ == "__main__":
    main()
