import requests
import csv
import os
import time
import signal
import sys
from datetime import datetime
from collections import defaultdict

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

    stats = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    with open(DATA_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pct = float(row["percent"]) if row["percent"] else 0.0
            stats[row["day_of_week"]][int(row["hour"])][row["location"]].append(pct)

    print("\n" + "=" * 62)
    print("  RPAC OCCUPANCY STATISTICS (avg % full by day & hour)")
    print("=" * 62)

    for day in DAYS:
        if day not in stats:
            continue
        print(f"\n  {day}:")
        for hour in sorted(stats[day].keys()):
            time_label = f"{hour:02d}:00-{hour:02d}:59"
            for loc, percents in sorted(stats[day][hour].items()):
                avg = round(sum(percents) / len(percents), 1)
                bar = "#" * int(avg / 5)
                print(f"    {time_label}  {loc:<30} {avg:>5}%  [{bar:<20}]  ({len(percents)} samples)")

    print("=" * 62 + "\n")


def poll_once():
    now = datetime.now()
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
        # Local continuous mode: python test.py --loop
        loop_mode()
    else:
        # Single-run mode used by GitHub Actions
        poll_once()
