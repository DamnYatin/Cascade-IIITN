"""Generate a fixture ``data/processed/maharashtra_climate.csv`` for Phase 1.

This is *fixture data*, not real IMD measurements. It reproduces the documented
structure (20 districts, daily 2019-01-01 to 2025-12-31) and the extreme-event
magnitudes cited in the playbook so the rainfall adapter presets can be verified
against it. Replace this file with the real export before any public demo.

Columns: date, district, latitude, longitude, rainfall, tmax, tmin, temperature
"""
from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np

OUT = Path("data/processed/maharashtra_climate.csv")

DISTRICTS = [
    ("Mumbai", 19.076, 72.878),
    ("Thane", 19.218, 72.978),
    ("Ratnagiri", 16.991, 73.312),
    ("Pune", 18.520, 73.856),
    ("Nashik", 19.997, 73.790),
    ("Nagpur", 21.146, 79.081),
    ("Aurangabad", 19.876, 75.343),
    ("Kolhapur", 16.695, 74.233),
    ("Solapur", 17.660, 75.910),
    ("Amravati", 20.935, 77.754),
    ("Nanded", 19.139, 77.312),
    ("Latur", 18.407, 76.559),
    ("Akola", 20.700, 77.008),
    ("Chandrapur", 19.958, 79.296),
    ("Gadchiroli", 20.176, 79.950),
    ("Bhandara", 21.159, 79.650),
    ("Wardha", 20.736, 78.608),
    ("Raigad", 18.478, 73.347),
    ("Sindhudurg", 16.274, 73.667),
    ("Dhule", 20.900, 74.770),
]

START = date(2019, 1, 1)
END = date(2025, 12, 31)

# Documented extremes (playbook): Mumbai 269 mm on 2019-06-29;
# Thane 360 mm on 2021-07-20; Mumbai 281 mm on 2021-07-19.
EXTREMES = {
    (date(2019, 6, 29), "Mumbai"): 269.0,
    (date(2021, 7, 20), "Thane"): 360.0,
    (date(2021, 7, 19), "Mumbai"): 281.0,
}


def monsoon_base(d: date, lat: float) -> float:
    """Typical daily mean rainfall (mm) by day-of-year, monsoon-weighted."""
    doy = d.timetuple().tm_yday
    # Monsoon peak mid-July (doy ~195-200)
    monsoon = math.exp(-0.5 * ((doy - 197) / 45) ** 2)
    base = 6.0 * monsoon
    # Pre-monsoon showers May-June
    if 120 <= doy <= 150:
        base += 2.0 * math.exp(-0.5 * ((doy - 135) / 10) ** 2)
    return max(0.0, base)


def main() -> None:
    rng = np.random.default_rng(7)
    rows = []
    d = START
    while d <= END:
        for name, lat, lon in DISTRICTS:
            base = monsoon_base(d, lat)
            rain = float(rng.gamma(shape=1.2, scale=base / 1.2 + 0.1))
            # Occasional heavy non-extreme days
            if rng.random() < 0.02:
                rain += float(rng.uniform(30, 90))
            key = (d, name)
            if key in EXTREMES:
                rain = EXTREMES[key]
            tmax = 30.0 + 5.0 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 100) / 365)
            tmin = tmax - 10.0
            temp = (tmax + tmin) / 2
            rows.append(
                [
                    d.isoformat(),
                    name,
                    f"{lat:.4f}",
                    f"{lon:.4f}",
                    f"{rain:.1f}",
                    f"{tmax:.1f}",
                    f"{tmin:.1f}",
                    f"{temp:.1f}",
                ]
            )
        d += timedelta(days=1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["date", "district", "latitude", "longitude", "rainfall", "tmax",
             "tmin", "temperature"]
        )
        w.writerows(rows)
    print(f"Wrote {OUT} with {len(rows)} rows "
          f"({START} to {END}, {len(DISTRICTS)} districts)")


if __name__ == "__main__":
    main()
