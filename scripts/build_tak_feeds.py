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

SOCAL_BBOX = {
    "xmin": -121.0,
    "ymin": 32.3,
    "xmax": -114.0,
    "ymax": 36.8,
    "spatialReference": {"wkid": 4326},
}

ALERTWEST_API = "https://api.cdn.prod.alertwest.com/api/firecams/v0/cameras"
CALOES_API = "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/CalOES_California_Webcams/FeatureServer/0/query"

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

def make_kml(cameras, title, out_file):
    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = title

    style = ET.SubElement(doc, "Style", id="camera-style")
    icon_style = ET.SubElement(style, "IconStyle")
    ET.SubElement(icon_style, "scale").text = "1.1"
    icon = ET.SubElement(icon_style, "Icon")