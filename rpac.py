import requests
import csv
import json
import os
import time
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

ET = ZoneInfo("America/New_York")

URL = "https://recsports.osu.edu/fms/Home/GetLocations"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://recsports.osu.edu/fms/facilities/rpac",
    "X-Requested-With": "XMLHttpRequest",
}
PARAMS = {"locationCode": "rpac"}
DATA_FILE = "rpac_stats.csv"
POLL_INTERVAL = 300  # seconds (5 minutes)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

AQUATIC_POOLS = {
    "RPAC Aquatic Center - Lap Pool",
    "RPAC Aquatic Center - Leisure Pool",
    "RPAC Aquatic Center - Class Pool",
    "RPAC Aquatic Center - Comp Pool",
    "RPAC Aquatic Center - Hot Tub",
}


def fetch_data():
    r = requests.get(URL, headers=HEADERS, params=PARAMS, timeout=10)
    r.raise_for_status()
    return r.json()


def save_record(timestamp, day, hour, name, count, capacity, percent):
    file_exists = os.path.exists(DATA_FILE)
    with open(DATA_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "day_of_week", "hour", "location", "count", "capacity", "percent"])
        writer.writerow([timestamp, day, hour, name, count, capacity, percent])


def print_stats():
    if not os.path.exists(DATA_FILE):
        print("No data collected yet.")
        return

    # month_num -> day -> hour -> location -> list of percents
    stats = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    month_names = {}

    with open(DATA_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row["percent"]:
                continue
            pct = float(row["percent"])
            dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            month_num = dt.month
            month_names[month_num] = dt.strftime("%B")
            stats[month_num][row["day_of_week"]][int(row["hour"])][row["location"]].append(pct)

    print("\n" + "=" * 62)
    print("  RPAC OCCUPANCY BY MONTH (avg % full per day & hour)")
    print("=" * 62)

    for month_num in sorted(stats.keys()):
        print(f"\n  {month_names[month_num]}:")
        for day in DAYS:
            if day not in stats[month_num]:
                continue
            print(f"\n    {day}:")
            for hour in sorted(stats[month_num][day].keys()):
                for loc, percents in sorted(stats[month_num][day][hour].items()):
                    avg = round(sum(percents) / len(percents), 1)
                    bar = "#" * int(avg / 5)
                    print(f"      {hour:02d}:00  {loc:<30} {avg:>5}%  [{bar:<20}]  ({len(percents)} samples)")

    print("=" * 62 + "\n")


GRID_FILE = "rpac_grid.csv"
HOURS = list(range(24))


def export_grid():
    if not os.path.exists(DATA_FILE):
        print("No data collected yet.")
        return

    # month_num -> location -> day -> hour -> list of percents
    stats = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    month_names = {}

    with open(DATA_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row["percent"]:
                continue
            pct = float(row["percent"])
            dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            month_num = dt.month
            month_names[month_num] = dt.strftime("%B")
            if row["location"] not in AQUATIC_POOLS:
                continue
            stats[month_num][row["location"]][row["day_of_week"]][int(row["hour"])].append(pct)

    with open(GRID_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        for month_num in sorted(stats.keys()):
            for loc in sorted(stats[month_num].keys()):
                writer.writerow([f"{month_names[month_num]} — {loc}"] + [""] * len(DAYS))
                writer.writerow(["Hour"] + DAYS)
                for hour in HOURS:
                    row = [f"{hour:02d}:00"]
                    for day in DAYS:
                        percents = stats[month_num][loc][day].get(hour, [])
                        row.append(round(sum(percents) / len(percents), 1) if percents else "")
                    writer.writerow(row)
                writer.writerow([])  # blank row between sections

    print(f"Grid exported to {os.path.abspath(GRID_FILE)}")


README_HOURS = list(range(8, 21))  # 8am to 8pm
SITE_URL = "https://drink36.github.io/tOSU-rpac-tracker/"


def export_readme():
    if not os.path.exists(DATA_FILE):
        print("No data collected yet.")
        return

    # location -> day -> hour -> list of percents (all months combined)
    stats = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    with open(DATA_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row["percent"]:
                continue
            if row["location"] not in AQUATIC_POOLS:
                continue
            pct = float(row["percent"])
            stats[row["location"]][row["day_of_week"]][int(row["hour"])].append(pct)

    updated = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    lines = []
    lines.append("# RPAC Aquatic Center Occupancy\n")
    lines.append("Wondering when is the best time to go swimming? This tracker collects live occupancy data from the **Recreation and Physical Activity Center (RPAC)** at **The Ohio State University** every 15 minutes and builds up a historical average so you can find the least crowded times to swim.\n")
    lines.append(f"**[📊 Open the interactive site]({SITE_URL})**: latest readings, best times for each day, and every area of the RPAC (gyms and fitness floors too).\n")
    lines.append(f"_Last updated: {updated}_\n")
    lines.append("Lower % = fewer people in the pool. Empty cells mean no data collected yet for that time slot.\n")

    for loc in sorted(stats.keys()):
        short = loc.replace("RPAC ", "")
        lines.append(f"\n## {short}\n")
        lines.append("| Hour | " + " | ".join(DAYS) + " |")
        lines.append("|------|" + "|".join(["-----"] * len(DAYS)) + "|")
        for hour in README_HOURS:
            cells = []
            has_data = False
            for day in DAYS:
                percents = stats[loc][day].get(hour, [])
                if percents:
                    cells.append(f"{round(sum(percents)/len(percents), 1)}%")
                    has_data = True
                else:
                    cells.append("")
            if has_data:
                lines.append(f"| {hour:02d}:00 | " + " | ".join(cells) + " |")

    with open("README.md", "w") as f:
        f.write("\n".join(lines) + "\n")

    print("README.md updated.")


SITE_DATA_FILE = os.path.join("docs", "data.json")
RECENT_DAYS = 60


def short_name(loc):
    name = loc.strip().replace("RPAC ", "").replace("Aquatic Center - ", "")
    return " ".join(name.replace(" - ", "–").replace("-", "–").split())


def location_group(loc):
    if "Aquatic" in loc:
        return "Pools"
    if "Gym" in loc or "Court" in loc:
        return "Gyms & Courts"
    return "Fitness"


def _grid(cells, value):
    """Turn {(day, hour): [samples]} into a 7x24 grid of averages (None = no data)."""
    grid = []
    for day in DAYS:
        row = []
        for hour in HOURS:
            samples = cells.get((day, hour))
            row.append(round(value(samples), 1) if samples else None)
        grid.append(row)
    return grid


def _summary(cells):
    return {
        "pct": _grid(cells, lambda s: sum(p for p, _ in s) / len(s)),
        "people": _grid(cells, lambda s: sum(c for _, c in s) / len(s)),
        "n": [[len(cells.get((d, h), [])) for h in HOURS] for d in DAYS],
    }


def iso(dt):
    """Timestamps in the CSV are ET wall-clock times; tag them so browsers read them right."""
    return dt.replace(tzinfo=ET).isoformat(timespec="seconds")


def export_site():
    """Write docs/data.json, the data behind the website (docs/index.html)."""
    if not os.path.exists(DATA_FILE):
        print("No data collected yet.")
        return

    rows = []
    with open(DATA_FILE, newline="") as f:
        for row in csv.DictReader(f):
            if not row["percent"]:
                continue
            dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            rows.append((dt, row["day_of_week"], int(row["hour"]), row["location"],
                         int(row["count"]), int(row["capacity"]), float(row["percent"])))
    if not rows:
        print("No data collected yet.")
        return

    first = min(r[0] for r in rows)
    last = max(r[0] for r in rows)
    recent_cutoff = last.timestamp() - RECENT_DAYS * 86400

    all_cells = defaultdict(lambda: defaultdict(list))     # loc -> (day, hour) -> [(pct, count)]
    recent_cells = defaultdict(lambda: defaultdict(list))
    latest = {}                                             # loc -> (dt, count, capacity, pct)

    for dt, day, hour, loc, count, cap, pct in rows:
        key = (day, hour)
        all_cells[loc][key].append((pct, count))
        if dt.timestamp() >= recent_cutoff:
            recent_cells[loc][key].append((pct, count))
        if loc not in latest or dt >= latest[loc][0]:
            latest[loc] = (dt, count, cap, pct)

    locations = []
    for loc in sorted(all_cells, key=lambda l: (["Pools", "Fitness", "Gyms & Courts"].index(location_group(l)), short_name(l))):
        dt, count, cap, pct = latest[loc]
        locations.append({
            "id": short_name(loc).lower().replace(" ", "-").replace("–", "-").replace("&", "and"),
            "name": short_name(loc),
            "group": location_group(loc),
            "capacity": cap,
            "latest": {"time": iso(dt), "count": count, "pct": pct},
            "recent": _summary(recent_cells[loc]),
            "all": _summary(all_cells[loc]),
        })

    data = {
        "generated": datetime.now(ET).isoformat(timespec="seconds"),
        "first": iso(first),
        "last": iso(last),
        "recentDays": RECENT_DAYS,
        "days": DAYS,
        "locations": locations,
    }

    os.makedirs(os.path.dirname(SITE_DATA_FILE), exist_ok=True)
    with open(SITE_DATA_FILE, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"Site data written to {os.path.abspath(SITE_DATA_FILE)}")


def poll_once():
    now = datetime.now(ET)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    day = DAYS[now.weekday()]
    hour = now.hour

    try:
        data = fetch_data()
        for loc in data["locations"]:
            name = loc["locationName"]
            count = int(loc.get("lastCount") or 0)
            capacity = int(loc.get("totalCapacity") or 0)
            percent = round(count / capacity * 100, 1) if capacity else None
            save_record(timestamp, day, hour, name, count, capacity, percent if percent is not None else "")
            print(f"[{timestamp}] {name}: {count}/{capacity} ({percent}%)")
    except Exception as e:
        print(f"[{timestamp}] Fetch error: {e}")


def loop_mode():
    """Run continuously, polling every POLL_INTERVAL seconds."""
    print(f"RPAC Tracker started — polling every {POLL_INTERVAL // 60} min.")
    print(f"Data saved to: {os.path.abspath(DATA_FILE)}")
    print("Press Ctrl+C to stop and view full statistics.\n")

    if os.path.exists(DATA_FILE):
        print("Existing data found — showing stats from previous runs:")
        print_stats()

    def handle_exit(*_):
        print("\nStopping tracker...")
        print_stats()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)

    poll_count = 0
    while True:
        poll_once()
        poll_count += 1
        if poll_count % 12 == 0:
            print_stats()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    if "--loop" in sys.argv:
        loop_mode()
    elif "--stats" in sys.argv:
        print_stats()
    elif "--grid" in sys.argv:
        export_grid()
    elif "--readme" in sys.argv:
        export_readme()
    elif "--site" in sys.argv:
        export_site()
    else:
        poll_once()
