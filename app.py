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


def hospitals_for(emergency):
    keys = {"Heart Attack": "heart", "Pregnancy": "pregnancy"}
    key = keys.get(emergency)

    # Accident aur Other me saare hospitals
    if key is None:
        return hospitals, False

    matched = []
    for h in hospitals:
        if key in services_for(h["name"]):
            matched.append(h)

    if len(matched) > 0:
        return matched, False

    # Koi nahi mila to saare dikhao aur note do
    return hospitals, True


def load_hospitals():
    # Moradabad ke hospitals OpenStreetMap (Nominatim) se laata hai
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": "hospital",
        "format": "json",
        "limit": 40,
        "viewbox": "78.65,28.92,78.90,28.76",
        "bounded": 1,
    }
    headers = {"User-Agent": "LifeLineRouteStudentProject/1.0"}
    try:
        data = requests.get(url, params=params, headers=headers, timeout=20).json()
    except Exception:
        return []

    found = []
    seen = set()
    for item in data:
        name = item["display_name"].split(",")[0].strip()
        lat = float(item["lat"])
        lon = float(item["lon"])
        key = name + str(round(lat, 3)) + str(round(lon, 3))
        if key not in seen:
            seen.add(key)
            found.append({"name": name, "lat": lat, "lon": lon})
    return found


def find_verified_hospitals(existing):
    # Tumhari list ke jo hospitals map ke 40 me nahi aaye, unhe naam se dhoondho
    added = []
    for title, info in VERIFIED.items():
        already = False
        for h in existing:
            if matches(h["name"], info):
                already = True
                break
        if already:
            continue

        queries = [title + " Moradabad", info["keywords"][0] + " hospital Moradabad"]
        for q in queries:
            time.sleep(1)  # search service ka rule: 1 second me 1 request
            try:
                data = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": q, "format": "json", "limit": 1,
                            "viewbox": "78.55,29.0,79.0,28.7", "bounded": 1},
                    headers={"User-Agent": "LifeLineRouteStudentProject/1.0"},
                    timeout=20,
                ).json()
            except Exception:
                data = []
            if len(data) > 0:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                added.append({"name": title, "lat": lat, "lon": lon})
                print(" + dhoondh liya:", title, lat, lon)
                break
    return added


hospitals = MANUAL_HOSPITALS + load_hospitals()
hospitals = hospitals + find_verified_hospitals(hospitals)

print("Hospitals mile:", len(hospitals))
for h in hospitals:
    print(" -", h["name"], "->", services_for(h["name"]))

print("")
print("Tumhari verified list ke ye hospitals map pe NAHI mile:")
missing = 0
for title, info in VERIFIED.items():
    found_it = False
    for h in hospitals:
        if matches(h["name"], info):
            found_it = True
            break
    if not found_it:
        print(" -", title)
        missing = missing + 1
if missing == 0:
    print(" (koi nahi, sab mil gaye)")


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
    global hospitals
    if len(hospitals) == 0:
        hospitals = MANUAL_HOSPITALS + load_hospitals()
    emergency = request.args.get("type", "Other")
    pool, fallback = hospitals_for(emergency)
    return jsonify({"list": pool, "fallback": fallback})


@app.route("/find-route", methods=["POST"])
def find_route():
    data = request.get_json()
    lat = data["lat"]
    lon = data["lon"]
    emergency = data.get("emergency", "Other")

    pool, fallback = hospitals_for(emergency)
    if len(pool) == 0:
        return jsonify({"error": "Hospital list is empty"}), 404

    # Pehle seedhi doori se 5 sabse paas wale hospitals
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

    if len(results) == 0:
        return jsonify({"error": "No route found"}), 404

    # Sabse kam time wala pehle
    results.sort(key=lambda r: r["time"])

    return jsonify({"best": results[0], "all": results})


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