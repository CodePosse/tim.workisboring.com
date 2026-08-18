#!/usr/bin/env python3

"""
NIFC / WFIGS Fire Layer Builder
===============================

Downloads current wildfire information from the public NIFC/WFIGS
ArcGIS FeatureServer and creates:

GeoJSON for the Leaflet web map:
    /atak/data/nifc/nifc-current-incidents.geojson
    /atak/data/nifc/nifc-current-perimeters.geojson

KML for ATAK / Google Earth:
    /atak/data/kml/nifc-current-incidents.kml
    /atak/data/kml/nifc-current-perimeters.kml

Network KML for ATAK:
    /atak/data/kml/nifc-current-incidents-network.kml
    /atak/data/kml/nifc-current-perimeters-network.kml

This file does NOT modify or remove any existing camera data.

Source:
    NIFC / WFIGS Current Wildfires

Layers:
    0 = Current_Incidents
    1 = Current_Perimeters
"""

from __future__ import annotations

import html
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent

DATA_DIR = SCRIPT_DIR / "data" / "nifc"
KML_DIR = SCRIPT_DIR / "data" / "kml"

INCIDENT_GEOJSON = DATA_DIR / "nifc-current-incidents.geojson"
PERIMETER_GEOJSON = DATA_DIR / "nifc-current-perimeters.geojson"

INCIDENT_KML = KML_DIR / "nifc-current-incidents.kml"
PERIMETER_KML = KML_DIR / "nifc-current-perimeters.kml"

INCIDENT_NETWORK_KML = KML_DIR / "nifc-current-incidents-network.kml"
PERIMETER_NETWORK_KML = KML_DIR / "nifc-current-perimeters-network.kml"


# Public URLs after deployment.
PUBLIC_BASE_URL = "https://tim.workisboring.com/atak/data/kml"

INCIDENT_PUBLIC_KML = (
    f"{PUBLIC_BASE_URL}/nifc-current-incidents.kml"
)

PERIMETER_PUBLIC_KML = (
    f"{PUBLIC_BASE_URL}/nifc-current-perimeters.kml"
)


# Official NIFC/WFIGS ArcGIS service.
FEATURE_SERVER = (
    "https://services9.arcgis.com/"
    "RHVPKKiFTONKtxq3/ArcGIS/rest/services/"
    "USA_Wildfires_v1/FeatureServer"
)

INCIDENT_LAYER = 0
PERIMETER_LAYER = 1


# Western United States bounding box.
#
# min longitude, min latitude, max longitude, max latitude
#
# Includes:
# California
# Oregon
# Washington
# Nevada
# Arizona
# Utah
# Idaho
# Montana
# New Mexico
# Colorado
#
WESTERN_US_BBOX = "-125,31,-102,49"


NETWORK_REFRESH_SECONDS = 900

HTTP_TIMEOUT = 60

USER_AGENT = (
    "tim.workisboring.com NIFC fire map builder/1.0 "
    "(https://tim.workisboring.com/atak/cameras.html)"
)


# ----------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------

def log(message: str) -> None:
    print(message, flush=True)


def escape(value: Any) -> str:
    return html.escape(
        str(value if value is not None else ""),
        quote=True,
    )


def cdata(value: Any) -> str:
    return str(value if value is not None else "").replace(
        "]]>",
        "]]]]><![CDATA[>",
    )


def first_value(
    properties: dict[str, Any],
    *keys: str,
    default: Any = "",
) -> Any:
    """
    Return the first non-empty property.

    NIFC/WFIGS schemas occasionally expose equivalent information using
    different field names, so the builder tolerates several common names.
    """

    for key in keys:
        value = properties.get(key)

        if value not in (
            None,
            "",
            "null",
            "None",
        ):
            return value

    return default


def atomic_write(
    path: Path,
    content: str,
) -> None:
    """
    Write a file atomically so a browser or ATAK client never sees a
    partially-written feed.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )

    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:

            handle.write(content)

            handle.flush()

            os.fsync(
                handle.fileno()
            )

        os.chmod(
            temporary_path,
            0o644,
        )

        os.replace(
            temporary_path,
            path,
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


# ----------------------------------------------------------------------
# NIFC download
# ----------------------------------------------------------------------

def build_query_url(
    layer_id: int,
) -> str:

    params = {
        "where": "1=1",

        "geometry": WESTERN_US_BBOX,

        "geometryType": (
            "esriGeometryEnvelope"
        ),

        "inSR": "4326",

        "spatialRel": (
            "esriSpatialRelIntersects"
        ),

        "outFields": "*",

        "returnGeometry": "true",

        "outSR": "4326",

        "f": "geojson",
    }

    query = urllib.parse.urlencode(
        params
    )

    return (
        f"{FEATURE_SERVER}/"
        f"{layer_id}/query?"
        f"{query}"
    )


def download_geojson(
    layer_id: int,
    layer_name: str,
) -> dict[str, Any]:

    url = build_query_url(
        layer_id
    )

    log(
        f"Downloading {layer_name}..."
    )

    request = urllib.request.Request(
        url,
        headers={
            "Accept": (
                "application/geo+json,"
                "application/json"
            ),
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=HTTP_TIMEOUT,
        ) as response:

            raw = response.read()

    except Exception as exc:
        raise RuntimeError(
            f"Unable to download "
            f"{layer_name}: {exc}"
        ) from exc

    try:
        payload = json.loads(
            raw.decode("utf-8")
        )

    except Exception as exc:
        raise RuntimeError(
            f"NIFC returned invalid JSON "
            f"for {layer_name}"
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            f"NIFC returned an unexpected "
            f"response for {layer_name}"
        )

    features = payload.get(
        "features"
    )

    if not isinstance(
        features,
        list,
    ):
        raise RuntimeError(
            f"NIFC response for "
            f"{layer_name} has no "
            f"features array"
        )

    log(
        f"{layer_name}: "
        f"{len(features)} features"
    )

    return payload


# ----------------------------------------------------------------------
# GeoJSON output
# ----------------------------------------------------------------------

def save_geojson(
    path: Path,
    payload: dict[str, Any],
) -> None:

    text = json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    )

    text += "\n"

    atomic_write(
        path,
        text,
    )

    log(
        f"Wrote {path}"
    )


# ----------------------------------------------------------------------
# Incident KML
# ----------------------------------------------------------------------

def incident_description(
    properties: dict[str, Any],
) -> str:

    incident_name = first_value(
        properties,
        "IncidentName",
        "IncidentNameClean",
        default="Unnamed Fire",
    )

    incident_type = first_value(
        properties,
        "IncidentTypeCategory",
        "IncidentTypeKind",
        "IncidentType",
    )

    acres = first_value(
        properties,
        "DailyAcres",
        "CalculatedAcres",
        "DiscoveryAcres",
    )

    percent_contained = first_value(
        properties,
        "PercentContained",
    )

    fire_cause = first_value(
        properties,
        "FireCause",
        "FireCauseGeneral",
    )

    discovery_date = first_value(
        properties,
        "FireDiscoveryDateTime",
        "DiscoveryDate",
    )

    jurisdiction = first_value(
        properties,
        "POOProtectingAgency",
        "PrimaryFireOrganization",
        "UnitOrOtherAgencyIdentifier",
    )

    irwin_id = first_value(
        properties,
        "IrwinID",
        "IRWINID",
    )

    lines = [
        f"<b>{escape(incident_name)}</b>",
        "Source: NIFC / WFIGS",
    ]

    if incident_type:
        lines.append(
            f"Type: {escape(incident_type)}"
        )

    if acres not in (
        None,
        "",
    ):
        lines.append(
            f"Acres: {escape(acres)}"
        )

    if percent_contained not in (
        None,
        "",
    ):
        lines.append(
            "Contained: "
            f"{escape(percent_contained)}%"
        )

    if fire_cause:
        lines.append(
            f"Cause: {escape(fire_cause)}"
        )

    if discovery_date:
        lines.append(
            "Discovery: "
            f"{escape(discovery_date)}"
        )

    if jurisdiction:
        lines.append(
            "Agency: "
            f"{escape(jurisdiction)}"
        )

    if irwin_id:
        lines.append(
            f"IRWIN ID: {escape(irwin_id)}"
        )

    return "<br>\n".join(
        lines
    )


def build_incident_kml(
    payload: dict[str, Any],
) -> str:

    placemarks: list[str] = []

    for feature in payload.get(
        "features",
        [],
    ):

        geometry = feature.get(
            "geometry"
        ) or {}

        properties = feature.get(
            "properties"
        ) or {}

        if geometry.get(
            "type"
        ) != "Point":
            continue

        coordinates = geometry.get(
            "coordinates"
        )

        if (
            not isinstance(
                coordinates,
                list,
            )
            or len(coordinates) < 2
        ):
            continue

        longitude = coordinates[0]
        latitude = coordinates[1]

        incident_name = first_value(
            properties,
            "IncidentName",
            "IncidentNameClean",
            default="Unnamed Fire",
        )

        description = cdata(
            incident_description(
                properties
            )
        )

        placemarks.append(
            f"""
    <Placemark>
      <name>🔥 {escape(incident_name)}</name>

      <styleUrl>#wildfireIncident</styleUrl>

      <description><![CDATA[
{description}
      ]]></description>

      <Point>
        <coordinates>{longitude},{latitude},0</coordinates>
      </Point>

    </Placemark>
"""
        )

    generated = datetime.now(
        timezone.utc
    ).isoformat()

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">

<Document>

  <name>NIFC Current Wildfire Incidents</name>

  <description>
    NIFC / WFIGS current wildfire incident points.
    Generated {escape(generated)}.
  </description>

  <Style id="wildfireIncident">

    <IconStyle>

      <scale>1.1</scale>

      <Icon>

        <href>
          https://maps.google.com/mapfiles/kml/shapes/firedept.png
        </href>

      </Icon>

    </IconStyle>

    <LabelStyle>
      <scale>0.85</scale>
    </LabelStyle>

  </Style>

  <Folder>

    <name>🔥 Current Wildfires</name>

{''.join(placemarks)}

  </Folder>

</Document>

</kml>
"""


# ----------------------------------------------------------------------
# Fire perimeter KML
# ----------------------------------------------------------------------

def perimeter_description(
    properties: dict[str, Any],
) -> str:

    incident_name = first_value(
        properties,
        "IncidentName",
        "IncidentNameClean",
        default="Unnamed Fire",
    )

    acres = first_value(
        properties,
        "GISAcres",
        "CalculatedAcres",
        "DailyAcres",
    )

    perimeter_date = first_value(
        properties,
        "DateCurrent",
        "CurrentDate",
        "CreateDate",
    )

    incident_type = first_value(
        properties,
        "IncidentTypeCategory",
        "IncidentTypeKind",
        "IncidentType",
    )

    lines = [
        f"<b>{escape(incident_name)}</b>",
        "Source: NIFC / WFIGS",
    ]

    if incident_type:
        lines.append(
            f"Type: {escape(incident_type)}"
        )

    if acres not in (
        None,
        "",
    ):
        lines.append(
            f"Acres: {escape(acres)}"
        )

    if perimeter_date:
        lines.append(
            "Perimeter Date: "
            f"{escape(perimeter_date)}"
        )

    return "<br>\n".join(
        lines
    )


def coordinates_to_kml(
    ring: list[Any],
) -> str:

    coordinates: list[str] = []

    for point in ring:

        if (
            not isinstance(
                point,
                list,
            )
            or len(point) < 2
        ):
            continue

        longitude = point[0]
        latitude = point[1]

        coordinates.append(
            f"{longitude},{latitude},0"
        )

    return " ".join(
        coordinates
    )


def polygon_to_kml(
    polygon: list[Any],
) -> str:

    if not polygon:
        return ""

    outer = coordinates_to_kml(
        polygon[0]
    )

    if not outer:
        return ""

    inner_boundaries: list[str] = []

    for inner_ring in polygon[1:]:

        inner = coordinates_to_kml(
            inner_ring
        )

        if not inner:
            continue

        inner_boundaries.append(
            f"""
        <innerBoundaryIs>
          <LinearRing>
            <coordinates>
              {inner}
            </coordinates>
          </LinearRing>
        </innerBoundaryIs>
"""
        )

    return f"""
      <Polygon>

        <tessellate>1</tessellate>

        <outerBoundaryIs>

          <LinearRing>

            <coordinates>
              {outer}
            </coordinates>

          </LinearRing>

        </outerBoundaryIs>

{''.join(inner_boundaries)}

      </Polygon>
"""


def geometry_to_kml(
    geometry: dict[str, Any],
) -> str:

    geometry_type = geometry.get(
        "type"
    )

    coordinates = geometry.get(
        "coordinates"
    )

    if geometry_type == "Polygon":

        return polygon_to_kml(
            coordinates or []
        )

    if geometry_type == "MultiPolygon":

        polygon_parts: list[str] = []

        for polygon in coordinates or []:

            converted = polygon_to_kml(
                polygon
            )

            if converted:
                polygon_parts.append(
                    converted
                )

        if not polygon_parts:
            return ""

        return f"""
      <MultiGeometry>
{''.join(polygon_parts)}
      </MultiGeometry>
"""

    return ""


def is_prescribed_fire(
    properties: dict[str, Any],
) -> bool:

    fields = [
        first_value(
            properties,
            "IncidentTypeCategory",
        ),
        first_value(
            properties,
            "IncidentTypeKind",
        ),
        first_value(
            properties,
            "IncidentType",
        ),
    ]

    joined = " ".join(
        str(value).lower()
        for value in fields
        if value
    )

    return (
        "prescribed" in joined
        or "rx" in joined.split()
    )


def build_perimeter_kml(
    payload: dict[str, Any],
) -> str:

    placemarks: list[str] = []

    for feature in payload.get(
        "features",
        [],
    ):

        geometry = feature.get(
            "geometry"
        ) or {}

        properties = feature.get(
            "properties"
        ) or {}

        geometry_kml = geometry_to_kml(
            geometry
        )

        if not geometry_kml:
            continue

        incident_name = first_value(
            properties,
            "IncidentName",
            "IncidentNameClean",
            default="Unnamed Fire",
        )

        prescribed = is_prescribed_fire(
            properties
        )

        style_url = (
            "#prescribedFire"
            if prescribed
            else "#wildfirePerimeter"
        )

        icon = (
            "🟠"
            if prescribed
            else "🔥"
        )

        description = cdata(
            perimeter_description(
                properties
            )
        )

        placemarks.append(
            f"""
    <Placemark>

      <name>
        {icon} {escape(incident_name)}
      </name>

      <styleUrl>{style_url}</styleUrl>

      <description><![CDATA[
{description}
      ]]></description>

{geometry_kml}

    </Placemark>
"""
        )

    generated = datetime.now(
        timezone.utc
    ).isoformat()

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">

<Document>

  <name>NIFC Current Fire Perimeters</name>

  <description>
    NIFC / WFIGS current wildfire perimeter polygons.
    Generated {escape(generated)}.
  </description>


  <!--
      KML color format is:

      AABBGGRR

      66 = approximately 40% opacity
  -->


  <Style id="wildfirePerimeter">

    <LineStyle>

      <color>ff0000ff</color>

      <width>3</width>

    </LineStyle>

    <PolyStyle>

      <color>660000ff</color>

      <fill>1</fill>

      <outline>1</outline>

    </PolyStyle>

  </Style>


  <Style id="prescribedFire">

    <LineStyle>

      <color>ff00a5ff</color>

      <width>3</width>

    </LineStyle>

    <PolyStyle>

      <color>6600a5ff</color>

      <fill>1</fill>

      <outline>1</outline>

    </PolyStyle>

  </Style>


  <Folder>

    <name>🔥 Current Fire Perimeters</name>

{''.join(placemarks)}

  </Folder>

</Document>

</kml>
"""


# ----------------------------------------------------------------------
# Network KML
# ----------------------------------------------------------------------

def build_network_kml(
    name: str,
    kml_url: str,
) -> str:

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">

<Document>

  <name>{escape(name)}</name>

  <NetworkLink>

    <name>{escape(name)}</name>

    <refreshVisibility>1</refreshVisibility>

    <flyToView>0</flyToView>

    <Link>

      <href>{escape(kml_url)}</href>

      <refreshMode>
        onInterval
      </refreshMode>

      <refreshInterval>
        {NETWORK_REFRESH_SECONDS}
      </refreshInterval>

      <viewRefreshMode>
        never
      </viewRefreshMode>

    </Link>

  </NetworkLink>

</Document>

</kml>
"""


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:

    log(
        "NIFC / WFIGS fire builder"
    )

    log(
        "Western US bounding box: "
        f"{WESTERN_US_BBOX}"
    )


    # --------------------------------------------------------------
    # Download
    # --------------------------------------------------------------

    incidents = download_geojson(
        INCIDENT_LAYER,
        "NIFC current incidents",
    )

    perimeters = download_geojson(
        PERIMETER_LAYER,
        "NIFC current perimeters",
    )


    # --------------------------------------------------------------
    # GeoJSON
    # --------------------------------------------------------------

    save_geojson(
        INCIDENT_GEOJSON,
        incidents,
    )

    save_geojson(
        PERIMETER_GEOJSON,
        perimeters,
    )


    # --------------------------------------------------------------
    # KML
    # --------------------------------------------------------------

    incident_kml = build_incident_kml(
        incidents
    )

    perimeter_kml = build_perimeter_kml(
        perimeters
    )

    atomic_write(
        INCIDENT_KML,
        incident_kml,
    )

    atomic_write(
        PERIMETER_KML,
        perimeter_kml,
    )

    log(
        f"Wrote {INCIDENT_KML}"
    )

    log(
        f"Wrote {PERIMETER_KML}"
    )


    # --------------------------------------------------------------
    # Network KML
    # --------------------------------------------------------------

    incident_network = build_network_kml(
        "NIFC Current Wildfire Incidents",
        INCIDENT_PUBLIC_KML,
    )

    perimeter_network = build_network_kml(
        "NIFC Current Fire Perimeters",
        PERIMETER_PUBLIC_KML,
    )

    atomic_write(
        INCIDENT_NETWORK_KML,
        incident_network,
    )

    atomic_write(
        PERIMETER_NETWORK_KML,
        perimeter_network,
    )

    log(
        f"Wrote {INCIDENT_NETWORK_KML}"
    )

    log(
        f"Wrote {PERIMETER_NETWORK_KML}"
    )


    # --------------------------------------------------------------
    # Summary
    # --------------------------------------------------------------

    incident_count = len(
        incidents.get(
            "features",
            [],
        )
    )

    perimeter_count = len(
        perimeters.get(
            "features",
            [],
        )
    )

    log("")
    log("SUCCESS")
    log(
        f"Incident points: {incident_count}"
    )
    log(
        f"Fire perimeters: {perimeter_count}"
    )
    log("")
    log(
        "No existing camera files were modified."
    )

    return 0


if __name__ == "__main__":

    try:

        raise SystemExit(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\nCancelled.",
            file=sys.stderr,
        )

        raise SystemExit(130)

    except Exception as exc:

        print(
            f"\nNIFC build failed: {exc}",
            file=sys.stderr,
        )

        raise SystemExit(1)
