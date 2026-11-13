# RPAC Crowd Tracker

Wondering when the pool at Ohio State's **RPAC** (Recreation and Physical Activity Center) is least crowded? This project records the head counts that RecSports publishes for every area of the RPAC and the other rec centers, and turns them into typical crowds by day and hour.

**[📊 Open the site](https://drink36.github.io/tOSU-rpac-tracker/)**: the latest counts, the quietest hours for any day, and a weekly heatmap for every pool, gym and fitness floor at the RPAC, North Rec, Jesse Owens North and South, and the ARC.

## How it works

- A GitHub Action reads the counts from the RecSports website and appends them to one CSV per rec center (`rpac_stats.csv`, `nrc_stats.csv`, `jon_stats.csv`, `jos_stats.csv`, `arc_stats.csv`). It's scheduled every 15 minutes, but GitHub runs it a few times a day in practice.
- RecSports staff enter the counts, so a number can sit unchanged for hours. A reading only counts when its number was updated shortly before it was recorded. Closed hours and counts left over from the night before are skipped.
- Pool counts are updated every few minutes. Gym and fitness counts are entered by hand, often hours apart, so the site shows their latest count but no hourly pattern.
- The site and the tables below default to the current semester, because summer hours and crowds are different.
- If a fetch fails, the run fails, and GitHub emails the repo owner.

## Run it locally

```bash
pip install -r requirements.txt
```

```bash
python rpac.py
```

That records one reading for every rec center. To rebuild the site data (`docs/data.json`), the tables below and `rpac_grid.csv`:

```bash
python rpac.py --site --readme --grid
```

To preview the site, serve the `docs` folder and open http://localhost:8000:

```bash
python -m http.server 8000 --directory docs
```

`python rpac.py --stats` prints RPAC averages by month, and `python rpac.py --loop` polls every 5 minutes until you press Ctrl+C.

## Typical crowds at the RPAC pools

Everything between the markers below is rewritten on every run; the rest of this file is safe to edit.

<!-- tables:start -->
_Average % full by hour: Autumn 2026 (Mon–Thu combined), data through Nov 13, 2026, 6:34 PM ET. A blank cell has fewer than 5 readings. [See every area on the site](https://drink36.github.io/tOSU-rpac-tracker/)._

### Class Pool (capacity 32)

| Hour | Mon–Thu | Fri | Sat | Sun |
|---|---|---|---|---|
| 6 AM | 14% |  |  |  |
| 7 AM | 12% |  |  |  |
| 8 AM | 18% | 8.1% |  |  |
| 9 AM | 11% |  |  |  |
| 10 AM | 16% | 8.1% |  |  |
| 11 AM | 7.2% |  | 12% |  |
| 12 PM | 11% |  |  |  |
| 1 PM | 12% | 15% |  |  |
| 2 PM | 14% |  | 14% |  |
| 3 PM | 15% | 15% |  | 11% |
| 4 PM | 23% |  |  |  |
| 5 PM | 19% | 22% |  | 18% |
| 6 PM | 24% | 21% |  | 18% |
| 7 PM | 16% |  | 12% |  |
| 8 PM | 10% |  |  |  |
| 9 PM | 6.2% |  |  |  |

### Comp Pool (capacity 25)

_Marked closed by RecSports at the last reading._

| Hour | Mon–Thu | Fri | Sat | Sun |
|---|---|---|---|---|
| 7 AM | 0.0% |  |  |  |
| 11 AM | 0.8% |  |  |  |
| 12 PM | 4.4% |  |  |  |
| 1 PM | 2.4% |  |  |  |
| 3 PM | 0.0% |  |  |  |
| 4 PM | 0.0% |  |  |  |
| 5 PM | 4.0% |  |  |  |
| 6 PM | 13% |  |  |  |
| 7 PM | 4.0% |  |  |  |
| 8 PM | 0.0% |  |  |  |
| 9 PM | 0.0% |  |  |  |

### Hot Tub (capacity 15)

| Hour | Mon–Thu | Fri | Sat | Sun |
|---|---|---|---|---|
| 6 AM | 1.3% |  |  |  |
| 7 AM | 6.7% |  |  |  |
| 8 AM | 1.3% | 17% |  |  |
| 9 AM | 4.7% |  |  |  |
| 10 AM | 2.7% | 2.7% |  |  |
| 11 AM | 6.0% |  | 6.7% |  |
| 12 PM | 9.3% |  |  |  |
| 1 PM | 10% | 11% |  | 9.3% |
| 2 PM | 11% |  | 15% |  |
| 3 PM | 10% | 13% |  | 12% |
| 4 PM | 23% |  |  |  |
| 5 PM | 19% | 21% |  | 23% |
| 6 PM | 33% | 39% |  | 37% |
| 7 PM | 27% |  | 11% |  |
| 8 PM | 38% |  |  |  |
| 9 PM | 33% |  |  |  |

### Lap Pool (capacity 24)

| Hour | Mon–Thu | Fri | Sat | Sun |
|---|---|---|---|---|
| 6 AM | 15% |  |  |  |
| 7 AM | 17% |  |  |  |
| 8 AM | 23% | 16% |  |  |
| 9 AM | 15% |  |  |  |
| 10 AM | 21% | 14% |  |  |
| 11 AM | 15% |  | 8.3% |  |
| 12 PM | 13% |  |  |  |
| 1 PM | 18% | 16% |  | 27% |
| 2 PM | 20% |  | 10% |  |
| 3 PM | 19% | 21% |  | 27% |
| 4 PM | 26% |  |  |  |
| 5 PM | 29% | 23% |  | 23% |
| 6 PM | 25% | 32% |  | 21% |
| 7 PM | 20% |  | 23% |  |
| 8 PM | 24% |  |  |  |
| 9 PM | 21% |  |  |  |

### Leisure Pool (capacity 40)

| Hour | Mon–Thu | Fri | Sat | Sun |
|---|---|---|---|---|
| 6 AM | 0.0% |  |  |  |
| 7 AM | 0.0% |  |  |  |
| 8 AM | 0.0% | 0.0% |  |  |
| 9 AM | 0.0% |  |  |  |
| 10 AM | 0.0% | 0.0% |  |  |
| 11 AM | 0.0% |  | 4.2% |  |
| 12 PM | 0.0% |  |  |  |
| 1 PM | 0.0% | 0.0% |  | 7.5% |
| 2 PM | 0.0% |  | 14% |  |
| 3 PM | 0.0% | 0.0% |  | 14% |
| 4 PM | 1.5% |  |  |  |
| 5 PM | 6.5% | 20% |  | 12% |
| 6 PM | 16% | 17% |  | 16% |
| 7 PM | 9.8% |  | 22% |  |
| 8 PM | 6.8% |  |  |  |
| 9 PM | 13% |  |  |  |
<!-- tables:end -->
