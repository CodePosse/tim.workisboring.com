#!/usr/bin/env bash
set -euo pipefail

SOURCE_URL="http://training.gotak.cloud:3000/deflock_us_conus.kml"
DESTINATION="/var/www/html/atak/data/kml/deflock-us-conus.kml"
TEMP_FILE="${DESTINATION}.tmp"

mkdir -p "$(dirname "$DESTINATION")"

curl \
  --fail \
  --location \
  --silent \
  --show-error \
  --connect-timeout 20 \
  --max-time 120 \
  "$SOURCE_URL" \
  --output "$TEMP_FILE"

# Basic validation: make sure it appears to be KML.
if ! grep -qE '<kml|<Document|<Placemark' "$TEMP_FILE"; then
    echo "Downloaded file does not look like KML" >&2
    rm -f "$TEMP_FILE"
    exit 1
fi

mv "$TEMP_FILE" "$DESTINATION"

echo "Updated $DESTINATION"
