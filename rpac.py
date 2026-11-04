"""Record how crowded Ohio State's rec centers are, and build the website from it.

RecSports publishes a head count for each area of each rec center. Every poll
appends one row per area to that center's CSV (rpac_stats.csv, nrc_stats.csv,
...). The exporters turn those rows into docs/data.json (the website), the
tables in README.md and rpac_grid.csv.

    python rpac.py                         poll every rec center once (exit code 1 if a fetch fails)
    python rpac.py --site --readme --grid  rebuild the outputs from the CSVs
    python rpac.py --stats                 print RPAC averages by month
    python rpac.py --loop                  poll every 5 minutes until Ctrl+C
"""

import argparse
import csv
import io
import json
import os
import re
import signal
import statistics
import sys
import time
from collections import defaultdict, namedtuple
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
TIME_FMT = "%Y-%m-%d %H:%M:%S"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOURS = list(range(24))

URL = "https://recsports.osu.edu/fms/Home/GetLocations"
LIVE_PAGE = "https://recsports.osu.edu/fms/facilities/{code}"
USER_AGENT = "tOSU-rpac-tracker (+https://github.com/drink36/tOSU-rpac-tracker)"
SITE_URL = "https://drink36.github.io/tOSU-rpac-tracker/"

# code: (name, how the site's headline refers to it, CSV file)
FACILITIES = {
    "rpac": ("RPAC", "the RPAC", "rpac_stats.csv"),
    "nrc": ("North Rec", "North Rec", "nrc_stats.csv"),
    "jon": ("Jesse Owens North", "Jesse Owens North", "jon_stats.csv"),
    "jos": ("Jesse Owens South", "Jesse Owens South", "jos_stats.csv"),
    "arc": ("ARC", "the ARC", "arc_stats.csv"),
}
DATA_FILE = FACILITIES["rpac"][2]
COLUMNS = ["timestamp", "day_of_week", "hour", "location", "count", "capacity", "percent",
           "updated", "closed", "location_id"]

POLL_INTERVAL = 300  # seconds, --loop only
FETCH_TRIES = 3
RETRY_WAIT = 15      # seconds between fetch attempts

# Which readings count? RecSports staff enter these numbers, so a count can sit
# unchanged for hours or days. Rows saved since Nov 2026 carry OSU's own "last
# updated" time and closed flag; for older rows, freshness is inferred.
FRESH_AFTER_UPDATE = timedelta(minutes=90)  # the count was entered at most this long before we read it
GROUP_QUIET = timedelta(hours=3)            # old rows: some area updated together with this one changed recently
FROZEN = timedelta(days=3)                  # old rows: this area's own count changed within this long
LIVE_SHARE = 0.5         # areas with at least this share of fresh daytime readings are "live"
MIN_READINGS = 5         # cells with fewer readings than this aren't ranked
TERM_MIN_DAYS = 21       # the semester view becomes the default once it has this many days of data

# Rough OSU calendar, by (month, day). The gap between Autumn and Spring is winter break.
TERMS = [
    ("Spring", (1, 8), (5, 7)),
    ("Summer", (5, 8), (8, 20)),
    ("Autumn", (8, 21), (12, 19)),
]
GROUP_ORDER = ["Pools", "Fitness", "Gyms & Courts"]

SITE_DATA_FILE = os.path.join("docs", "data.json")
GRID_FILE = "rpac_grid.csv"
README_FILE = "README.md"
README_START = "<!-- tables:start -->"
README_END = "<!-- tables:end -->"


# ---------------------------------------------------------------- names

def clean_name(name):
    return " ".join(name.split())


def short_name(name):
    """'RPAC Aquatic Center - Lap Pool' -> 'Lap Pool', 'JON - Tennis Court 1 - 2' -> 'Tennis Court 1–2'."""
    name = clean_name(name)
    for prefix in ("RPAC ", "Aquatic Center - ", "NRC ", "JON - ", "JON ", "JOS ", "ARC "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return re.sub(r"\s*-\s*", "–", name)


def location_group(name):
    if re.search(r"Pool|Hot Tub|Aquatic", name):
        return "Pools"
    if re.search(r"Gym|Court|Turf", name):
        return "Gyms & Courts"
    return "Fitness"


def update_group(name):
    """Areas whose counts RecSports staff update together."""
    return "pools" if location_group(name) == "Pools" else "other"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", short_name(name).lower()).strip("-")


def term_of(day):
    """(label, first day) of the semester or break that contains `day`."""
    for name, start, end in TERMS:
        if start <= (day.month, day.day) <= end:
            return f"{name} {day.year}", date(day.year, *start)
    year = day.year if day.month == 12 else day.year - 1
    return f"Winter break {year}–{str(year + 1)[2:]}", date(year, 12, 20)


def iso(dt):
    """CSV times are ET wall-clock times; tag them so browsers read them right."""
    return dt.replace(tzinfo=ET).isoformat(timespec="seconds")


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- polling

def parse_updated(value):
    """OSU's lastUpdatedDateAndTimeUTC ('2026-11-04T22:37:08.3070000Z') as ET wall-clock text."""
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)", str(value or ""))
    if not m or int(m.group(1)) < 2000:
        return ""
    utc = datetime(*map(int, m.groups()), tzinfo=timezone.utc)
    return utc.astimezone(ET).strftime(TIME_FMT)


def fetch_data(code="rpac"):
    """Fetch and validate one rec center's counts. Raises on anything unexpected."""
    r = requests.get(URL, params={"locationCode": code}, timeout=10, headers={
        "User-Agent": USER_AGENT,
        "Referer": LIVE_PAGE.format(code=code),
        "X-Requested-With": "XMLHttpRequest",
    })
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        raise ValueError(f"response is not JSON (HTTP {r.status_code}, "
                         f"{r.headers.get('content-type')}): {r.text[:200]!r}") from None
    locations = payload.get("locations") if isinstance(payload, dict) else None
    if not locations:
        raise ValueError(f"no locations in the response: {r.text[:200]!r}")
    for loc in locations:
        count = str(loc.get("lastCount", "")).strip()
        capacity = str(loc.get("totalCapacity", "")).strip()
        if not loc.get("locationName") or not count.isdigit() or not capacity.isdigit():
            raise ValueError(f"unexpected entry: {json.dumps(loc)[:200]}")
    return locations


def to_row(loc, now):
    count = int(str(loc["lastCount"]).strip())
    capacity = int(str(loc["totalCapacity"]).strip())
    closed = {"true": "1", "false": "0"}.get(str(loc.get("isClosed", "")).strip().lower(), "")
    return [
        now.strftime(TIME_FMT), DAYS[now.weekday()], now.hour, loc["locationName"],
        count, capacity, round(count / capacity * 100, 1) if capacity else "",
        parse_updated(loc.get("lastUpdatedDateAndTimeUTC")), closed, str(loc.get("locationId") or ""),
    ]


def ensure_header(path):
    """Create the CSV, or add the newer columns to an older header (old rows leave them blank)."""
    text = ""
    if os.path.exists(path):
        with open(path, newline="") as f:
            text = f.read()
    if not text.strip():
        buf = io.StringIO()
        csv.writer(buf).writerow(COLUMNS)
        write_atomic(path, buf.getvalue())
        return
    first, _, rest = text.partition("\n")
    header = first.rstrip("\r").split(",")
    if header == COLUMNS:
        return
    if header != COLUMNS[:len(header)]:
        raise ValueError(f"{path} has an unexpected header: {first!r}")
    write_atomic(path, ",".join(COLUMNS) + "\r\n" + rest)


def poll_facility(code, now):
    """Fetch one rec center (with retries) and append its rows. Returns True on success."""
    for attempt in range(1, FETCH_TRIES + 1):
        try:
            locations = fetch_data(code)
            break
        except Exception as e:  # network errors, bad JSON, unexpected format
            print(f"[{code}] attempt {attempt}/{FETCH_TRIES} failed: {e}")
            if attempt == FETCH_TRIES:
                return False
            time.sleep(RETRY_WAIT)
    rows = [to_row(loc, now) for loc in locations]
    path = FACILITIES[code][2]
    ensure_header(path)
    with open(path, "a", newline="") as f:
        csv.writer(f).writerows(rows)
    for row in rows:
        closed = " (closed)" if row[8] == "1" else ""
        print(f"[{row[0]}] {code} {clean_name(row[3])}: {row[4]}/{row[5]}{closed}, counted {row[7] or '?'}")
    return True


def poll_once():
    """Poll every rec center once. Returns True only if all of them worked."""
    now = datetime.now(ET)
    results = [poll_facility(code, now) for code in FACILITIES]
    return all(results)


# ---------------------------------------------------------------- reading the CSVs

Reading = namedtuple("Reading", "time key name count capacity updated closed")
Observation = namedtuple("Observation", "reading status when")


def load_readings(path):
    """Read one rec center's CSV, oldest first."""
    if not os.path.exists(path):
        return []
    raw = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f, restval=""):
            capacity = int(r["capacity"] or 0)
            if not capacity:
                continue
            raw.append((
                datetime.strptime(r["timestamp"], TIME_FMT),
                clean_name(r["location"]),
                (r.get("location_id") or "").strip(),
                int(r["count"]),
                capacity,
                datetime.strptime(r["updated"], TIME_FMT) if r.get("updated") else None,
                {"1": True, "0": False}.get(r.get("closed") or ""),
            ))
    # Old rows have no location id: borrow it from newer rows with the same name,
    # so an area renamed by OSU keeps its history.
    ids = {name: lid for _, name, lid, *_ in raw if lid}
    readings = [Reading(t, lid or ids.get(name) or name, name, count, capacity, updated, closed)
                for t, name, lid, count, capacity, updated, closed in raw]
    readings.sort(key=lambda r: r.time)
    return readings


def classify(readings):
    """Decide which readings show what was really there at the time.

    status is one of:
      fresh   the count was entered shortly before we read it
      stale   the count had been sitting unchanged (overnight leftovers, frozen counts)
      closed  RecSports marked the area closed, or every area in its group read 0 (reset at closing)
      repeat  the same OSU update we already counted at an earlier poll
    `when` is when the count was taken: OSU's update time when we have it.
    """
    snapshots = defaultdict(list)
    for r in readings:
        snapshots[r.time].append(r)
    previous, run_start, last_change, counted = {}, {}, {}, set()
    out = []
    for t in sorted(snapshots):
        snap = snapshots[t]
        open_counts = defaultdict(list)
        for r in snap:
            group = update_group(r.name)
            if previous.get(r.key) != r.count:
                run_start[r.key] = t
                last_change[group] = t
            previous[r.key] = r.count
            if not r.closed:
                open_counts[group].append(r.count)
        reset = {g for g, counts in open_counts.items() if len(counts) >= 3 and not any(counts)}
        for r in snap:
            if r.closed or update_group(r.name) in reset:
                out.append(Observation(r, "closed", t))
            elif r.updated is not None:
                age = t - r.updated
                if (r.key, r.updated) in counted:
                    out.append(Observation(r, "repeat", t))
                elif timedelta(minutes=-10) <= age <= FRESH_AFTER_UPDATE:
                    counted.add((r.key, r.updated))
                    out.append(Observation(r, "fresh", r.updated))
                else:
                    out.append(Observation(r, "stale", t))
            else:
                fresh = (t - last_change[update_group(r.name)] <= GROUP_QUIET
                         and t - run_start[r.key] <= FROZEN)
                out.append(Observation(r, "fresh" if fresh else "stale", t))
    return out


def cell_stats(values):
    """[mean, 25th percentile, 75th percentile, readings, readings above 0], in people."""
    if not values:
        return None
    if len(values) == 1:
        q1 = q3 = float(values[0])
    else:
        q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return [round(statistics.fmean(values), 1), round(q1, 1), round(q3, 1), len(values),
            sum(1 for v in values if v > 0)]


@lru_cache(maxsize=None)
def facility_summary(code):
    """Everything the site shows for one rec center, or None if there's no data yet."""
    name, title, path = FACILITIES[code]
    readings = load_readings(path)
    if not readings:
        return None
    first, last = readings[0].time, readings[-1].time
    term_label, term_start = term_of(last.date())
    views = {
        "term": {"label": term_label, "since": term_start,
                 "columns": ["Mon–Thu", "Fri", "Sat", "Sun"], "dayColumn": [0, 0, 0, 0, 1, 2, 3]},
        "all": {"label": "All data", "since": first.date(),
                "columns": list(DAYS), "dayColumn": list(range(7))},
    }
    cells = {v: defaultdict(lambda: defaultdict(list)) for v in views}  # view -> key -> (column, hour) -> counts
    days_with_data = {v: set() for v in views}
    latest, since, previous = {}, {}, {}
    daytime = defaultdict(lambda: [0, 0])  # key -> [fresh, all] open daytime readings in the last 30 days

    for o in classify(readings):
        r = o.reading
        if previous.get(r.key) != r.count:
            since[r.key] = r.time
        previous[r.key] = r.count
        latest[r.key] = o
        if r.time >= last - timedelta(days=30) and 8 <= r.time.hour < 20 and o.status != "closed":
            daytime[r.key][0] += o.status == "fresh"
            daytime[r.key][1] += 1
        if o.status != "fresh":
            continue
        for v, spec in views.items():
            if o.when.date() >= spec["since"]:
                cells[v][r.key][(spec["dayColumn"][o.when.weekday()], o.when.hour)].append(r.count)
                days_with_data[v].add(o.when.date())

    locations, used = [], set()
    for key, o in latest.items():
        r = o.reading
        if r.time < last - timedelta(days=14):
            continue  # OSU no longer reports this area
        sid = slug(r.name)
        while sid in used:
            sid += "-x"
        used.add(sid)
        fresh, total = daytime[key]
        locations.append({
            "id": sid,
            "name": short_name(r.name),
            "group": location_group(r.name),
            "capacity": r.capacity,
            "live": None if total < 10 else fresh / total >= LIVE_SHARE,
            "latest": {
                "time": iso(r.time),
                "updated": iso(r.updated) if r.updated else None,
                "since": iso(since[key]),
                "count": r.count,
                "status": o.status,
                "closedByOsu": bool(r.closed),
            },
            "stats": {v: [[cell_stats(cells[v][key].get((c, h))) for h in HOURS]
                          for c in range(len(spec["columns"]))]
                      for v, spec in views.items()},
        })
    locations.sort(key=lambda l: (GROUP_ORDER.index(l["group"]), l["name"]))

    return {
        "code": code,
        "name": name,
        "title": title,
        "livePage": LIVE_PAGE.format(code=code),
        "first": iso(first),
        "last": iso(last),
        "defaultView": "term" if len(days_with_data["term"]) >= TERM_MIN_DAYS else "all",
        "views": {v: {"label": s["label"], "since": s["since"].isoformat(), "days": len(days_with_data[v]),
                      "columns": s["columns"], "dayColumn": s["dayColumn"]}
                  for v, s in views.items()},
        "locations": locations,
    }


# ---------------------------------------------------------------- exports

def export_site():
    """Write docs/data.json, the data behind the website (docs/index.html)."""
    facilities = [f for f in (facility_summary(code) for code in FACILITIES) if f]
    if not facilities:
        print("No data collected yet.")
        return
    data = {
        "version": 2,
        "minReadings": MIN_READINGS,
        "last": max(facilities, key=lambda f: datetime.fromisoformat(f["last"]))["last"],
        "facilities": facilities,
    }
    os.makedirs(os.path.dirname(SITE_DATA_FILE), exist_ok=True)
    write_atomic(SITE_DATA_FILE, json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print(f"Site data written to {SITE_DATA_FILE}")


def fmt_pct(value):
    return f"{value:.1f}%" if value < 10 else f"{value:.0f}%"


def readme_tables(fac):
    view = fac["views"][fac["defaultView"]]
    last = datetime.fromisoformat(fac["last"])
    when = f"{last:%b} {last.day}, {last.year}, {last.hour % 12 or 12}:{last:%M} {'AM' if last.hour < 12 else 'PM'} ET"
    combined = " (Mon–Thu combined)" if fac["defaultView"] == "term" else ""
    lines = [
        f"_Average % full by hour: {view['label']}{combined}, data through {when}. "
        f"A blank cell has fewer than {MIN_READINGS} readings. "
        f"[See every area on the site]({SITE_URL})._",
    ]
    for loc in fac["locations"]:
        if loc["group"] != "Pools":
            continue
        grid = loc["stats"][fac["defaultView"]]
        rows = []
        for h in HOURS:
            cells = [grid[c][h] for c in range(len(view["columns"]))]
            if not any(c and c[3] >= MIN_READINGS for c in cells):
                continue
            text = [fmt_pct(c[0] / loc["capacity"] * 100) if c and c[3] >= MIN_READINGS else "" for c in cells]
            rows.append(f"| {h % 12 or 12} {'AM' if h < 12 else 'PM'} | " + " | ".join(text) + " |")
        lines.append(f"\n### {loc['name']} (capacity {loc['capacity']})\n")
        if loc["latest"]["closedByOsu"]:
            lines.append("_Marked closed by RecSports at the last reading._\n")
        if rows:
            lines.append("| Hour | " + " | ".join(view["columns"]) + " |")
            lines.append("|---" * (len(view["columns"]) + 1) + "|")
            lines.extend(rows)
        else:
            lines.append("Not enough readings yet.")
    return "\n".join(lines)


def export_readme():
    """Replace the tables between the markers in README.md; the rest of the file is hand-written."""
    fac = facility_summary("rpac")
    if not fac:
        print("No data collected yet.")
        return
    block = f"{README_START}\n{readme_tables(fac)}\n{README_END}"
    text = ""
    if os.path.exists(README_FILE):
        with open(README_FILE) as f:
            text = f.read()
    if README_START in text and README_END in text:
        before, _, rest = text.partition(README_START)
        _, _, after = rest.partition(README_END)
        text = before + block + after
    else:
        text = text.rstrip() + "\n\n## Typical crowds at the RPAC pools\n\n" + block + "\n"
    write_atomic(README_FILE, text)
    print("README.md tables updated.")


def export_grid():
    """rpac_grid.csv: RPAC pools, average % full by day and hour for each month."""
    stats = defaultdict(lambda: defaultdict(list))  # (year, month, pool) -> (weekday, hour) -> percents
    for o in classify(load_readings(DATA_FILE)):
        r = o.reading
        if o.status == "fresh" and location_group(r.name) == "Pools":
            stats[(o.when.year, o.when.month, short_name(r.name))][(o.when.weekday(), o.when.hour)].append(
                r.count / r.capacity * 100)
    buf = io.StringIO()
    writer = csv.writer(buf)
    for year, month, pool in sorted(stats):
        cells = stats[(year, month, pool)]
        writer.writerow([f"{date(year, month, 1):%B %Y} — {pool}"] + [""] * len(DAYS))
        writer.writerow(["Hour"] + DAYS)
        for h in HOURS:
            row = [f"{h:02d}:00"]
            for d in range(7):
                values = cells.get((d, h))
                row.append(round(statistics.fmean(values), 1) if values else "")
            writer.writerow(row)
        writer.writerow([])
    write_atomic(GRID_FILE, buf.getvalue())
    print(f"Grid exported to {GRID_FILE}")


def print_stats():
    """Average % full per month, day and hour for every RPAC area (fresh readings only)."""
    stats = defaultdict(lambda: defaultdict(list))  # (year, month) -> (weekday, hour, area) -> percents
    for o in classify(load_readings(DATA_FILE)):
        if o.status == "fresh":
            r = o.reading
            stats[(o.when.year, o.when.month)][(o.when.weekday(), o.when.hour, short_name(r.name))].append(
                r.count / r.capacity * 100)
    if not stats:
        print("No data collected yet.")
        return
    print("\n" + "=" * 66)
    print("  RPAC OCCUPANCY BY MONTH (avg % full per day & hour, fresh readings)")
    print("=" * 66)
    for year, month in sorted(stats):
        print(f"\n  {date(year, month, 1):%B %Y}:")
        for d, day in enumerate(DAYS):
            keys = sorted(k for k in stats[(year, month)] if k[0] == d)
            if keys:
                print(f"\n    {day}:")
            for _, hour, area in keys:
                values = stats[(year, month)][(d, hour, area)]
                avg = statistics.fmean(values)
                print(f"      {hour:02d}:00  {area:<28} {avg:5.1f}%  [{'#' * int(avg / 5):<20}]  ({len(values)} readings)")
    print("=" * 66 + "\n")


def loop_mode():
    """Poll every POLL_INTERVAL seconds until Ctrl+C, then print statistics."""
    print(f"RPAC Tracker started, polling every {POLL_INTERVAL // 60} min. Press Ctrl+C to stop.\n")

    def handle_exit(*_):
        print("\nStopping tracker...")
        facility_summary.cache_clear()
        print_stats()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    while True:
        poll_once()
        time.sleep(POLL_INTERVAL)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Track how crowded Ohio State's rec centers are. "
                                                 "With no options, poll every rec center once.")
    parser.add_argument("--site", action="store_true", help="rebuild docs/data.json")
    parser.add_argument("--readme", action="store_true", help="rebuild the tables in README.md")
    parser.add_argument("--grid", action="store_true", help="rebuild rpac_grid.csv")
    parser.add_argument("--stats", action="store_true", help="print RPAC averages by month")
    parser.add_argument("--loop", action="store_true", help=f"poll every {POLL_INTERVAL // 60} minutes until Ctrl+C")
    args = parser.parse_args(argv)
    if args.loop:
        loop_mode()
    if not (args.site or args.readme or args.grid or args.stats):
        return 0 if poll_once() else 1
    if args.stats:
        print_stats()
    if args.site:
        export_site()
    if args.readme:
        export_readme()
    if args.grid:
        export_grid()
    return 0


if __name__ == "__main__":
    sys.exit(main())
