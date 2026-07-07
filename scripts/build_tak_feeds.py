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

ALERTWEST_API = "https://api.cdn.prod.alertwest.com/api/firecams/v0/cameras"
CALOES_API = "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/CalOES_California_Webcams/FeatureServer/0/query"

SOCAL_BBOX = {
    "xmin": -121.0,
    "ymin": 32.3,
    "xmax": -114.0,
    "ymax": 36.8,
    "spatialReference": {"wkid": 4326},
}

def pick(obj, keys, default=""):
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    return default

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

def write_json(filename, cameras):
    payload = {
        "generated_at": int(time.time()),
        "count": len(cameras),
        "cameras": cameras,
    }
    (DATA_DIR / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")

def make_kml(cameras, title, out_file):
    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = title

    style = ET.SubElement(doc, "Style", id="camera-style")
    icon_style = ET.SubElement(style, "IconStyle")
    ET.SubElement(icon_style, "scale").text = "1.1"
    icon = ET.SubElement(icon_style, "Icon")
    ET.SubElement(icon, "href").text = "https://maps.google.com/mapfiles/kml/shapes/camera.png"

    folder = ET.SubElement(doc, "Folder")
    ET.SubElement(folder, "name").text = title

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

    ET.ElementTree(kml).write(OUT_DIR / out_file, encoding="utf-8", xml_declaration=True)

def make_network_kml(title, href, out_file):
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{title} Auto Refresh</name>
    <NetworkLink>
      <name>{title}</name>
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
    (OUT_DIR / out_file).write_text(content, encoding="utf-8")

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
            "category": "Fire Camera",
            "lat": lat,
            "lon": lon,
            "county": site.get("county") or "",
            "heading": pos.get("pan") or "",
            "thumbnail": image.get("url") or "",
            "url": image.get("url") or "https://alertcalifornia.org/",
        })

    return cameras

def fetch_caloes():
    cameras = []
    r = requests.get(CALOES_API, params=arcgis_params(), timeout=30)
    r.raise_for_status()

    for feature in r.json().get("features", []):
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}

        lat = geom.get("y")
        lon = geom.get("x")
        if lat is None or lon is None:
            continue

        cameras.append({
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

    return cameras

def main():
    alertwest = fetch_alertwest()
    caloes = fetch_caloes()

    write_json("alertwest-cameras.json", alertwest)
    write_json("caloes-webcams.json", caloes)

    make_kml(alertwest, "ALERTCalifornia / AlertWest Cameras", "alertca.kml")
    make_kml(caloes, "Cal OES Webcams", "caloes-webcams.kml")

    make_network_kml(
        "ALERTCalifornia / AlertWest Cameras",
        "https://tim.workisboring.com/atak/alertca.kml",
        "alertca-network.kml",
    )

    make_network_kml(
        "Cal OES Webcams",
        "https://tim.workisboring.com/atak/caloes-webcams.kml",
        "caloes-network.kml",
    )

    print(f"AlertWest: {len(alertwest)}")
    print(f"Cal OES: {len(caloes)}")

if __name__ == "__main__":
    main()