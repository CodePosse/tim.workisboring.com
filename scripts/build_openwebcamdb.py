#!/usr/bin/env python3
"""
Build isolated OpenWebcamDB JSON and KML feeds.

Outputs:
    /var/www/html/atak/data/openwebcamdb-cameras.json
    /var/www/html/atak/openwebcamdb-cameras.kml
    /var/www/html/atak/openwebcamdb-network.kml

Important behavior:
    - Does not touch any other camera source.
    - Honors HTTP 429 Retry-After.
    - Enforces a minimum interval between API requests.
    - Uses list summaries without unnecessary detail requests.
    - Preserves existing output files when no usable cameras are returned.
    - Writes output atomically.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://openwebcamdb.com/api/v1"

OUTPUT_JSON = Path("/var/www/html/atak/data/openwebcamdb-cameras.json")
OUTPUT_KML = Path("/var/www/html/atak/openwebcamdb-cameras.kml")
OUTPUT_NETWORK_KML = Path("/var/www/html/atak/openwebcamdb-network.kml")

PUBLIC_KML_URL = (
    "https://tim.workisboring.com/atak/openwebcamdb-cameras.kml"
)

USER_AGENT = (
    "tim.workisboring.com OpenWebcamDB KML Builder/1.0 "
    "(https://tim.workisboring.com/atak/cameras.html)"
)

# Free API limit is five requests per minute.
# Thirteen seconds provides a small safety margin.
DEFAULT_REQUEST_INTERVAL = 13.0
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 5
DEFAULT_PAGE_SIZE = 20

# Do not make detail requests unless explicitly enabled.
DEFAULT_FETCH_DETAILS = False

# Protect the free daily request allowance.
DEFAULT_MAX_REQUESTS = 25


class ApiError(RuntimeError):
    """Raised when the OpenWebcamDB API cannot be read safely."""


@dataclass
class RequestBudget:
    maximum: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.maximum:
            raise ApiError(
                f"Request budget exhausted: {self.used}/{self.maximum}"
            )
        self.used += 1


class RateLimitedClient:
    def __init__(
        self,
        api_key: str | None,
        request_interval: float,
        timeout: int,
        max_retries: int,
        request_budget: RequestBudget,
    ) -> None:
        self.api_key = api_key
        self.request_interval = max(0.0, request_interval)
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_budget = request_budget
        self.last_request_started: float | None = None

    def _wait_for_request_slot(self) -> None:
        if self.last_request_started is None:
            return

        elapsed = time.monotonic() - self.last_request_started
        remaining = self.request_interval - elapsed

        if remaining > 0:
            print(
                f"Rate-limit pause: sleeping {remaining:.1f} seconds",
                flush=True,
            )
            time.sleep(remaining)

    @staticmethod
    def _retry_after_from_payload(payload: Any) -> int | None:
        if not isinstance(payload, dict):
            return None

        values = [
            payload.get("retry_after"),
            payload.get("retryAfter"),
        ]

        error = payload.get("error")
        if isinstance(error, dict):
            values.extend(
                [
                    error.get("retry_after"),
                    error.get("retryAfter"),
                ]
            )

        for value in values:
            try:
                seconds = int(float(value))
                if seconds >= 0:
                    return seconds
            except (TypeError, ValueError):
                continue

        return None

    @staticmethod
    def _retry_after_from_headers(headers: Any) -> int | None:
        if headers is None:
            return None

        value = headers.get("Retry-After")
        if value is None:
            return None

        try:
            seconds = int(float(value))
            if seconds >= 0:
                return seconds
        except (TypeError, ValueError):
            pass

        return None

    def get_json(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        url = f"{API_BASE}{endpoint}{query}"

        for attempt in range(1, self.max_retries + 1):
            self._wait_for_request_slot()
            self.request_budget.consume()
            self.last_request_started = time.monotonic()

            headers = {
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            }

            if self.api_key:
                # OpenWebcamDB deployments may accept one of these forms.
                # Supplying both is harmless when one is ignored.
                headers["Authorization"] = f"Bearer {self.api_key}"
                headers["X-API-Key"] = self.api_key

            request = Request(url, headers=headers, method="GET")

            print(
                f"GET {url} "
                f"[request {self.request_budget.used}/"
                f"{self.request_budget.maximum}]",
                flush=True,
            )

            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                    payload = json.loads(raw)

                    print(
                        f"HTTP {response.status}: {url}",
                        flush=True,
                    )
                    return payload

            except HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")

                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {}

                if exc.code == 429:
                    header_wait = self._retry_after_from_headers(exc.headers)
                    payload_wait = self._retry_after_from_payload(payload)

                    wait_seconds = max(
                        header_wait or 0,
                        payload_wait or 0,
                        int(self.request_interval),
                        1,
                    )

                    print(
                        f"HTTP 429 from {url}. "
                        f"retry_after={wait_seconds}; "
                        f"attempt {attempt}/{self.max_retries}",
                        file=sys.stderr,
                        flush=True,
                    )

                    if attempt >= self.max_retries:
                        raise ApiError(
                            f"OpenWebcamDB continued returning HTTP 429 "
                            f"after {self.max_retries} attempts"
                        ) from exc

                    # Add one second so we do not retry exactly on the boundary.
                    time.sleep(wait_seconds + 1)
                    continue

                if 500 <= exc.code < 600 and attempt < self.max_retries:
                    wait_seconds = min(60, 2 ** attempt)

                    print(
                        f"HTTP {exc.code}; retrying in "
                        f"{wait_seconds} seconds",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(wait_seconds)
                    continue

                raise ApiError(
                    f"OpenWebcamDB HTTP error {exc.code}: {raw}"
                ) from exc

            except URLError as exc:
                if attempt >= self.max_retries:
                    raise ApiError(
                        f"OpenWebcamDB network error: {exc}"
                    ) from exc

                wait_seconds = min(60, 2 ** attempt)
                print(
                    f"Network error: {exc}; retrying in "
                    f"{wait_seconds} seconds",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(wait_seconds)

            except json.JSONDecodeError as exc:
                raise ApiError(
                    f"OpenWebcamDB returned invalid JSON from {url}"
                ) from exc

        raise ApiError(f"Unable to retrieve {url}")


def first_value(
    item: dict[str, Any],
    *paths: str,
    default: Any = None,
) -> Any:
    """
    Read the first non-empty value from a sequence of dotted paths.

    Supports API variations such as:
        latitude
        location.latitude
        coordinates.lat
    """

    for path in paths:
        current: Any = item

        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]

        if current not in (None, ""):
            return current

    return default


def as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if result != result:
        return None

    return result


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("webcams", "data", "results", "items"):
        value = payload.get(key)

        if isinstance(value, list):
            return [
                item for item in value
                if isinstance(item, dict)
            ]

        if isinstance(value, dict):
            for nested_key in ("webcams", "results", "items", "data"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [
                        item for item in nested
                        if isinstance(item, dict)
                    ]

    return []


def has_next_page(
    payload: Any,
    item_count: int,
    page_size: int,
) -> bool:
    if not isinstance(payload, dict):
        return item_count >= page_size

    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        pagination = {}

    explicit_next = first_value(
        payload,
        "next",
        "next_page",
        "links.next",
        "meta.next_page",
        default=None,
    )

    if explicit_next not in (None, "", False):
        return True

    current_page = first_value(
        pagination,
        "page",
        "current_page",
        default=first_value(
            payload,
            "page",
            "current_page",
            "meta.current_page",
            default=None,
        ),
    )

    total_pages = first_value(
        pagination,
        "total_pages",
        "last_page",
        default=first_value(
            payload,
            "total_pages",
            "last_page",
            "meta.total_pages",
            default=None,
        ),
    )

    try:
        if current_page is not None and total_pages is not None:
            return int(current_page) < int(total_pages)
    except (TypeError, ValueError):
        pass

    return item_count >= page_size


def webcam_slug(item: dict[str, Any]) -> str:
    return str(
        first_value(
            item,
            "slug",
            "id",
            "webcam_id",
            "uuid",
            default="",
        )
    ).strip()


def normalize_webcam(item: dict[str, Any]) -> dict[str, Any] | None:
    latitude = as_float(
        first_value(
            item,
            "latitude",
            "lat",
            "location.latitude",
            "location.lat",
            "coordinates.latitude",
            "coordinates.lat",
        )
    )

    longitude = as_float(
        first_value(
            item,
            "longitude",
            "lng",
            "lon",
            "location.longitude",
            "location.lng",
            "location.lon",
            "coordinates.longitude",
            "coordinates.lng",
            "coordinates.lon",
        )
    )

    if latitude is None or longitude is None:
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    slug = webcam_slug(item)

    title = str(
        first_value(
            item,
            "title",
            "name",
            "webcam.name",
            default=slug or "OpenWebcamDB camera",
        )
    ).strip()

    city = str(
        first_value(
            item,
            "city",
            "location.city",
            default="",
        )
    ).strip()

    region = str(
        first_value(
            item,
            "region",
            "state",
            "location.region",
            "location.state",
            default="",
        )
    ).strip()

    country = str(
        first_value(
            item,
            "country",
            "country.name",
            "location.country",
            "location.country.name",
            default="",
        )
    ).strip()

    description = str(
        first_value(
            item,
            "description",
            "summary",
            default="",
        )
    ).strip()

    image_url = str(
        first_value(
            item,
            "image_url",
            "image",
            "thumbnail_url",
            "thumbnail",
            "preview_url",
            "preview",
            "images.current.preview",
            default="",
        )
    ).strip()

    stream_url = str(
        first_value(
            item,
            "stream_url",
            "stream.url",
            "player_url",
            "embed_url",
            default="",
        )
    ).strip()

    webpage_url = str(
        first_value(
            item,
            "url",
            "webcam_url",
            "page_url",
            "link",
            default="",
        )
    ).strip()

    if not webpage_url and slug:
        webpage_url = f"https://openwebcamdb.com/webcams/{slug}"

    location_parts = [
        part for part in (city, region, country) if part
    ]

    return {
        "id": slug or f"{latitude},{longitude}",
        "slug": slug,
        "name": title,
        "description": description,
        "latitude": latitude,
        "longitude": longitude,
        "city": city,
        "region": region,
        "country": country,
        "location": ", ".join(location_parts),
        "imageUrl": image_url,
        "streamUrl": stream_url,
        "url": webpage_url,
        "source": "OpenWebcamDB",
    }


def merge_detail(
    summary: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(summary)

    detail_data = detail.get("data")
    if isinstance(detail_data, dict):
        merged.update(detail_data)
    else:
        merged.update(detail)

    return merged


def collect_webcams(
    client: RateLimitedClient,
    max_pages: int,
    page_size: int,
    fetch_details: bool,
    max_detail_requests: int,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        payload = client.get_json(
            "/webcams",
            {
                "page": page,
                "limit": page_size,
            },
        )

        page_items = extract_items(payload)

        print(
            f"Page {page}: {len(page_items)} webcam summaries returned",
            flush=True,
        )

        if not page_items:
            break

        summaries.extend(page_items)

        if not has_next_page(payload, len(page_items), page_size):
            break

    if not fetch_details:
        print(
            "Detail requests disabled; using list summaries only.",
            flush=True,
        )
        raw_items = summaries
    else:
        raw_items = []
        detail_requests = 0

        for summary in summaries:
            normalized_summary = normalize_webcam(summary)

            # A detail request is only justified when a useful camera URL
            # is absent from the summary.
            needs_detail = (
                normalized_summary is None
                or (
                    not normalized_summary.get("streamUrl")
                    and not normalized_summary.get("url")
                )
            )

            slug = webcam_slug(summary)

            if (
                needs_detail
                and slug
                and detail_requests < max_detail_requests
            ):
                print(
                    f"Fetching required detail for {slug}",
                    flush=True,
                )

                detail = client.get_json(f"/webcams/{slug}")
                raw_items.append(merge_detail(summary, detail))
                detail_requests += 1
            else:
                raw_items.append(summary)

        print(
            f"Detail requests made: {detail_requests}",
            flush=True,
        )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in raw_items:
        webcam = normalize_webcam(item)
        if webcam is None:
            continue

        dedupe_key = str(webcam["id"])
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        normalized.append(webcam)

    normalized.sort(
        key=lambda camera: (
            str(camera.get("country", "")).lower(),
            str(camera.get("region", "")).lower(),
            str(camera.get("city", "")).lower(),
            str(camera.get("name", "")).lower(),
        )
    )

    return normalized


def cdata(value: Any) -> str:
    text = str(value or "")
    return text.replace("]]>", "]]]]><![CDATA[>")


def build_description(camera: dict[str, Any]) -> str:
    sections: list[str] = []

    description = str(camera.get("description", "")).strip()
    location = str(camera.get("location", "")).strip()
    image_url = str(camera.get("imageUrl", "")).strip()
    stream_url = str(camera.get("streamUrl", "")).strip()
    page_url = str(camera.get("url", "")).strip()

    sections.append("<strong>Source:</strong> OpenWebcamDB")

    if location:
        sections.append(
            f"<strong>Location:</strong> {html.escape(location)}"
        )

    if description:
        sections.append(f"<p>{html.escape(description)}</p>")

    if image_url:
        safe_image = html.escape(image_url, quote=True)
        sections.append(
            f'<p><img src="{safe_image}" '
            f'alt="" style="max-width:320px;height:auto"></p>'
        )

    if stream_url:
        safe_stream = html.escape(stream_url, quote=True)
        sections.append(
            f'<p><a href="{safe_stream}">Open camera stream</a></p>'
        )

    if page_url:
        safe_page = html.escape(page_url, quote=True)
        sections.append(
            f'<p><a href="{safe_page}">'
            f"Open OpenWebcamDB camera page</a></p>"
        )

    return "\n".join(sections)


def build_camera_kml(cameras: list[dict[str, Any]]) -> str:
    generated = datetime.now(timezone.utc).isoformat()

    placemarks: list[str] = []

    for camera in cameras:
        name = html.escape(str(camera.get("name", "Camera")))
        description = cdata(build_description(camera))
        longitude = camera["longitude"]
        latitude = camera["latitude"]

        placemarks.append(
            f"""    <Placemark>
      <name>{name}</name>
      <description><![CDATA[{description}]]></description>
      <styleUrl>#openwebcamdb-camera</styleUrl>
      <ExtendedData>
        <Data name="source"><value>OpenWebcamDB</value></Data>
        <Data name="cameraId"><value>{html.escape(str(camera["id"]))}</value></Data>
      </ExtendedData>
      <Point>
        <coordinates>{longitude},{latitude},0</coordinates>
      </Point>
    </Placemark>"""
        )

    body = "\n".join(placemarks)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>OpenWebcamDB Cameras</name>
    <description>Generated {html.escape(generated)}</description>

    <Style id="openwebcamdb-camera">
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

    <Folder>
      <name>OpenWebcamDB</name>
      <open>0</open>
{body}
    </Folder>
  </Document>
</kml>
"""


def build_network_kml(refresh_seconds: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>OpenWebcamDB Network Link</name>
    <NetworkLink>
      <name>OpenWebcamDB Cameras</name>
      <open>0</open>
      <Link>
        <href>{html.escape(PUBLIC_KML_URL)}</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>{refresh_seconds}</refreshInterval>
        <viewRefreshMode>never</viewRefreshMode>
      </Link>
    </NetworkLink>
  </Document>
</kml>
"""


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )

    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def backup_existing(path: Path) -> None:
    if not path.exists():
        return

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)


def publish(cameras: list[dict[str, Any]], refresh_seconds: int) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()

    json_document = {
        "source": "OpenWebcamDB",
        "generatedAt": generated_at,
        "count": len(cameras),
        "cameras": cameras,
    }

    json_text = json.dumps(
        json_document,
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    camera_kml = build_camera_kml(cameras)
    network_kml = build_network_kml(refresh_seconds)

    for path in (OUTPUT_JSON, OUTPUT_KML, OUTPUT_NETWORK_KML):
        backup_existing(path)

    write_atomic(OUTPUT_JSON, json_text)
    write_atomic(OUTPUT_KML, camera_kml)
    write_atomic(OUTPUT_NETWORK_KML, network_kml)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build isolated OpenWebcamDB JSON and KML feeds."
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Maximum list pages to retrieve. Default: 10",
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Requested page size. Default: {DEFAULT_PAGE_SIZE}",
    )

    parser.add_argument(
        "--request-interval",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL,
        help=(
            "Minimum seconds between API requests. "
            f"Default: {DEFAULT_REQUEST_INTERVAL}"
        ),
    )

    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help=(
            "Maximum total API requests during one run. "
            f"Default: {DEFAULT_MAX_REQUESTS}"
        ),
    )

    parser.add_argument(
        "--fetch-details",
        action="store_true",
        default=DEFAULT_FETCH_DETAILS,
        help=(
            "Allow selective individual webcam detail requests. "
            "Disabled by default."
        ),
    )

    parser.add_argument(
        "--max-detail-requests",
        type=int,
        default=0,
        help=(
            "Maximum individual detail requests. Default: 0. "
            "Requires --fetch-details."
        ),
    )

    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=3600,
        help="NetworkLink refresh interval. Default: 3600",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    api_key = (
        os.environ.get("OPENWEBCAMDB_API_KEY")
        or os.environ.get("OPENWEBCAMDB_TOKEN")
    )

    budget = RequestBudget(maximum=max(1, args.max_requests))

    client = RateLimitedClient(
        api_key=api_key,
        request_interval=args.request_interval,
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
        request_budget=budget,
    )

    try:
        cameras = collect_webcams(
            client=client,
            max_pages=max(1, args.max_pages),
            page_size=max(1, args.page_size),
            fetch_details=args.fetch_details,
            max_detail_requests=max(0, args.max_detail_requests),
        )

        if not cameras:
            print(
                "OpenWebcamDB returned zero usable cameras; "
                "preserving all previous output files.",
                file=sys.stderr,
            )
            return 2

        publish(cameras, args.refresh_seconds)

        print(
            f"Published {len(cameras)} OpenWebcamDB cameras.",
            flush=True,
        )
        print(f"JSON: {OUTPUT_JSON}", flush=True)
        print(f"KML: {OUTPUT_KML}", flush=True)
        print(f"Network KML: {OUTPUT_NETWORK_KML}", flush=True)
        print(
            f"API requests used: {budget.used}/{budget.maximum}",
            flush=True,
        )

        return 0

    except ApiError as exc:
        print(
            f"OpenWebcamDB build failed: {exc}",
            file=sys.stderr,
        )
        print(
            "Existing JSON and KML files were not changed.",
            file=sys.stderr,
        )
        return 1

    except Exception as exc:
        print(
            f"Unexpected OpenWebcamDB build failure: {exc}",
            file=sys.stderr,
        )
        print(
            "Existing JSON and KML files were not changed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())