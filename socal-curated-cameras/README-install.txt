Southern California Curated Camera Feed
=========================================

Files
-----
build_curated_socal_cameras.py
    Converts the JSON catalog to KML and NetworkLink KML.

curated-socal-cameras.json
    Starter camera catalog. Add, disable, or edit entries here.

Generated server files
----------------------
/var/www/html/atak/curated-socal-cameras.kml
/var/www/html/atak/curated-socal-network.kml

Install
-------
sudo mkdir -p /var/www/html/scripts /var/www/html/atak/data

sudo install -m 755 build_curated_socal_cameras.py \
  /var/www/html/scripts/build_curated_socal_cameras.py

sudo install -m 644 curated-socal-cameras.json \
  /var/www/html/atak/data/curated-socal-cameras.json

sudo /usr/bin/python3 \
  /var/www/html/scripts/build_curated_socal_cameras.py

Validation
----------
python3 -m json.tool \
  /var/www/html/atak/data/curated-socal-cameras.json >/dev/null \
  && echo "JSON OK"

xmllint --noout \
  /var/www/html/atak/curated-socal-cameras.kml \
  && echo "Camera KML OK"

xmllint --noout \
  /var/www/html/atak/curated-socal-network.kml \
  && echo "Network KML OK"

curl -I https://tim.workisboring.com/atak/curated-socal-cameras.kml
curl -I https://tim.workisboring.com/atak/curated-socal-network.kml

Optional URL validation
-----------------------
sudo /usr/bin/python3 \
  /var/www/html/scripts/build_curated_socal_cameras.py \
  --check-only

Notes
-----
The optional URL checker performs one GET per listed URL. Do not schedule it
frequently. The normal KML build makes no network requests.

To disable a camera without deleting it, set:
"enabled": false

Cron
----
sudo crontab -e

Add:
17 4 * * * /usr/bin/python3 /var/www/html/scripts/build_curated_socal_cameras.py >> /var/log/curated-socal-cameras.log 2>&1

A daily cron build is sufficient because the KML contains links to live camera
pages; it does not cache camera images.
