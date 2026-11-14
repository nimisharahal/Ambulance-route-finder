import re
import time
from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# Agar koi hospital map pe nahi aaya to yahan khud daalo (optional)
# Naam me wo keyword hona chahiye jo neeche VERIFIED me likha hai
MANUAL_HOSPITALS = [
    # {"name": "TMU Hospital", "lat": 28.827069, "lon": 78.658736},
]

# Tumhari verified list
VERIFIED = {
    "TMU Hospital": {"keywords": ["tmu", "teerthanker"], "services": ["heart"]},
    "Asian Vivekanand Super Specialty Hospital": {"keywords": ["vivekanand"], "services": ["heart", "pregnancy"]},
    "Ujala Cygnus Brightstar Hospital": {"keywords": ["ujala", "cygnus"], "services": ["heart", "pregnancy"]},
    "Sri Sai Hospital": {"keywords": ["sri sai"], "services": ["heart"]},
    "Cosmos Hospital": {"keywords": ["cosmos"], "services": ["heart", "pregnancy"]},
    "Vishwakarma Hospital & Heart Care Centre": {"keywords": ["vishwakarma"], "services": ["heart"]},
    "Mansarovar Nursing Home": {"keywords": ["mansarovar"], "services": ["pregnancy"]},
    "Dhanwantri Superspecialty Hospital": {"keywords": ["dhanwantri"], "services": ["pregnancy"]},
    "Apex Hospital": {"keywords": ["apex"], "services": ["pregnancy"]},
    "Shashi Prabha Hospital": {"keywords": ["shashi prabha", "shashiprabha"], "services": ["pregnancy"]},
}

def norm(text):
    # Sirf letters aur numbers rakho, baaki hata do
    return re.sub(r"[^a-z0-9]", "", text.lower())

def matches(name, info):
    n = norm(name)
    for k in info["keywords"]:
        if norm(k) in n:
            return True
    return False

def services_for(name):
    services = []
    for info in VERIFIED.values():
        if matches(name, info):
            for s in info["services"]:
                if s not in services:
                    services.append(s)
    return services

def hospitals_for(hospitals, emergency):
    keys = {
        "Heart Attack": "heart",
        "Pregnancy": "pregnancy"
    }

    key = keys.get(emergency)

    if key is None:
        return hospitals, False

    matched = []

    for h in hospitals:
        if key in services_for(h["name"]):
            matched.append(h)

    if matched:
        return matched, False

    return hospitals, True


def load_hospitals(lat=28.82, lon=78.78, radius=15000):
    url = "https://overpass.kumi.systems/api/interpreter"

    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="hospital"](around:{radius},{lat},{lon});
      way["amenity"="hospital"](around:{radius},{lat},{lon});
      relation["amenity"="hospital"](around:{radius},{lat},{lon});
      node["healthcare"="hospital"](around:{radius},{lat},{lon});
      way["healthcare"="hospital"](around:{radius},{lat},{lon});
      relation["healthcare"="hospital"](around:{radius},{lat},{lon});
    );
    out center tags;
    """

    try:
        response = requests.post(
            url,
            data={"data": query},
            headers={"User-Agent": "LifeLineRouteStudentProject/1.0"},
            timeout=35
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print("Hospital search error:", e)
        return []

    found = []
    seen = set()

    for item in data.get("elements", []):
        name = item.get("tags", {}).get("name")
        if not name:
            continue

        location = item.get("center", item)
        if "lat" not in location or "lon" not in location:
            continue

        lat_value = float(location["lat"])
        lon_value = float(location["lon"])

        key = (round(lat_value, 5), round(lon_value, 5))
        if key not in seen:
            seen.add(key)
            found.append({
                "name": name,
                "lat": lat_value,
                "lon": lon_value
            })

    return found

def get_route(lat, lon, hlat, hlon, name):
    # OSRM se asli road ka time, distance aur raasta mangao
    url = ("https://router.project-osrm.org/route/v1/driving/"
           + str(lon) + "," + str(lat) + ";"
           + str(hlon) + "," + str(hlat)
           + "?overview=full&geometries=geojson")
    reply = requests.get(url, timeout=20).json()
    if reply.get("code") != "Ok":
        return None
    route = reply["routes"][0]
    return {
        "name": name,
        "hlat": hlat,
        "hlon": hlon,
        "time": round(route["duration"] / 60, 1),
        "distance": round(route["distance"] / 1000, 2),
        "geometry": route["geometry"]["coordinates"],
    }

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/hospitals")
def get_hospitals():
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "Location coordinates are required"}), 400

    emergency = request.args.get("type", "Other")

    nearby_hospitals = MANUAL_HOSPITALS + load_hospitals(
        lat=lat,
        lon=lon,
        radius=15000
    )

    pool, fallback = hospitals_for(nearby_hospitals, emergency)

    return jsonify({
        "list": pool,
        "fallback": fallback
    })

@app.route("/find-route", methods=["POST"])
def find_route():
    data = request.get_json()

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Valid location is required"}), 400

    emergency = data.get("emergency", "Other")

    nearby_hospitals = MANUAL_HOSPITALS + load_hospitals(
        lat=lat,
        lon=lon,
        radius=15000
    )

    pool, fallback = hospitals_for(nearby_hospitals, emergency)

    if not pool:
        return jsonify({"error": "No nearby hospitals found"}), 404

    nearest = sorted(
        pool,
        key=lambda h: (h["lat"] - lat) ** 2 + (h["lon"] - lon) ** 2
    )[:5]

    results = []

    for h in nearest:
        try:
            r = get_route(lat, lon, h["lat"], h["lon"], h["name"])
        except Exception:
            return jsonify({"error": "Internet or route server problem"}), 500

        if r is not None:
            results.append(r)

    if not results:
        return jsonify({"error": "No route found"}), 404

    results.sort(key=lambda r: r["time"])

    return jsonify({
        "best": results[0],
        "all": results,
        "fallback": fallback
    })

@app.route("/route-to", methods=["POST"])
def route_to():
    data = request.get_json()
    try:
        r = get_route(data["lat"], data["lon"], data["hlat"], data["hlon"], data["name"])
    except Exception:
        return jsonify({"error": "Internet or route server problem"}), 500
    if r is None:
        return jsonify({"error": "No route found"}), 404
    return jsonify({"best": r, "all": [r]})


if __name__ == "__main__":
    app.run(debug=True)
