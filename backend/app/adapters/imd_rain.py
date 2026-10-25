"""IMD rainfall adapter: daily district rainfall -> hourly intensity.

Reads ``data/processed/maharashtra_climate.csv`` (path configurable) with columns::

    date, district, latitude, longitude, rainfall, tmax, tmin, temperature

Each daily rainfall total is disaggregated into 24 hourly intensities using a
seeded stochastic storm-shape that *exactly conserves* the daily total. The
resulting hourly observations carry ``source_kind="disaggregated"`` so they are
never mistaken for real sub-daily measurements.

The real rainfall can be fed in as the exogenous series for the synthetic
generator (``generator.generate_city(..., rain_series=...)``), giving a
"real rain, simulated downstream systems" demo.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from ..schemas import Observation, QualityFlag, SourceKind

DEFAULT_CSV_PATH = "data/processed/maharashtra_climate.csv"

REQUIRED_COLUMNS = {
    "date", "district", "latitude", "longitude", "rainfall", "tmax", "tmin", "temperature"
}

# Documented extreme events (values come from the source CSV).
#   Mumbai, late June - early July 2019:  Mumbai 269 mm on 2019-06-29
#   Konkan, mid - late July 2021:         Thane 360 mm on 2021-07-20,
#                                         Mumbai 281 mm on 2021-07-19
PRESETS = {
    "mumbai_2019": {
        "label": "Mumbai late June - early July 2019",
        "districts": ["Mumbai"],
        "start": "2019-06-28",
        "end": "2019-07-04",
        "check": [("Mumbai", date(2019, 6, 29), 269.0)],
    },
    "konkan_2021": {
        "label": "Konkan (Thane / Mumbai / Ratnagiri) mid - late July 2021",
        "districts": ["Thane", "Mumbai", "Ratnagiri"],
        "start": "2021-07-18",
        "end": "2021-07-22",
        "check": [
            ("Thane", date(2021, 7, 20), 360.0),
            ("Mumbai", date(2021, 7, 19), 281.0),
        ],
    },
}


@dataclass
class DailyRow:
    date: date
    district: str
    latitude: float
    longitude: float
    rainfall: float
    tmax: Optional[float]
    tmin: Optional[float]
    temperature: Optional[float]


class IMDRainAdapter:
    def __init__(self, csv_path: str | Path = DEFAULT_CSV_PATH, seed: int = 0):
        self.csv_path = Path(csv_path)
        self.seed = seed
        self._rows: list[DailyRow] = []
        self._loaded = False

    # ------------------------------------------------------------------ load
    def load(self) -> "IMDRainAdapter":
        """Load the CSV. Raises FileNotFoundError / ValueError with a clear
        message if the file is missing or malformed."""
        if not self.csv_path.exists():
            raise FileNotFoundError(
                f"IMD climate CSV not found: {self.csv_path}. "
                "Generate it first (see docs/PHASE1.md) or point --rain-csv at "
                "a real export with columns "
                "date,district,latitude,longitude,rainfall,tmax,tmin,temperature."
            )
        rows: list[DailyRow] = []
        with self.csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"CSV {self.csv_path} missing columns: {sorted(missing)}"
                )
            for i, rec in enumerate(reader, start=2):
                try:
                    d = datetime.strptime(rec["date"].strip(), "%Y-%m-%d").date()
                    rows.append(
                        DailyRow(
                            date=d,
                            district=rec["district"].strip(),
                            latitude=float(rec["latitude"]),
                            longitude=float(rec["longitude"]),
                            rainfall=float(rec["rainfall"] or 0.0),
                            tmax=_opt_float(rec["tmax"]),
                            tmin=_opt_float(rec["tmin"]),
                            temperature=_opt_float(rec["temperature"]),
                        )
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(
                        f"CSV {self.csv_path} malformed at line {i}: {exc}"
                    ) from exc
        self._rows = rows
        self._loaded = True
        return self

    def _require_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # --------------------------------------------------- storm disaggregation
    def disaggregate_daily(
        self, daily_total: float, seed: int, storm_peak_hour: int = 15
    ) -> list[float]:
        """Split one daily total into 24 hourly intensities.

        The hourly values sum to ``daily_total`` (within floating-point
        tolerance). A storm shape centred on ``storm_peak_hour`` plus seeded
        jitter determines the intra-day distribution.
        """
        rng = np.random.default_rng(seed)
        hours = np.arange(24)
        # Storm shape: peak in the afternoon, skewed toward evening.
        shape = np.exp(-0.5 * ((hours - storm_peak_hour) / 4.0) ** 2)
        shape = shape * (1.0 + 0.25 * rng.standard_normal(24))
        shape = np.clip(shape, 0.0, None)
        if shape.sum() <= 0:
            shape = np.ones(24)
        hourly = float(daily_total) * (shape / shape.sum())
        # Small multiplicative jitter, then rescale so the total is conserved.
        jitter = rng.normal(0.0, 0.02, 24)
        hourly = hourly * (1.0 + jitter)
        hourly = np.clip(hourly, 0.0, None)
        if hourly.sum() > 0:
            hourly = hourly * (float(daily_total) / hourly.sum())
        return [round(float(v), 4) for v in hourly]

    # ------------------------------------------------------- series queries
    def _district_rows(self, district: str) -> list[DailyRow]:
        self._require_loaded()
        return [r for r in self._rows if r.district == district]

    def daily_for_district(
        self, district: str, start: date | str, end: date | str
    ) -> list[DailyRow]:
        """Daily rows for ``district`` within [start, end] (inclusive)."""
        self._require_loaded()
        if isinstance(start, str):
            start = datetime.strptime(start, "%Y-%m-%d").date()
        if isinstance(end, str):
            end = datetime.strptime(end, "%Y-%m-%d").date()
        rows = self._district_rows(district)
        return [r for r in rows if start <= r.date <= end]

    def to_rain_series(
        self,
        district: str,
        start: date,
        end: date,
        seed: Optional[int] = None,
    ) -> dict[datetime, float]:
        """Hourly rainfall (mm) for ``district`` over [start, end] as a
        datetime-keyed series. Suitable as the generator's ``rain_series`` input
        (convert to hour offsets via ``(dt - start_time).total_seconds()//3600``)."""
        s = seed if seed is not None else self.seed
        series: dict[datetime, float] = {}
        day_seed = s
        for row in self.daily_for_district(district, start, end):
            hourly = self.disaggregate_daily(row.rainfall, day_seed)
            day_seed += 1  # distinct but deterministic seed per day
            for hh, v in enumerate(hourly):
                dt = datetime(
                    row.date.year, row.date.month, row.date.day, hh, tzinfo=timezone.utc
                )
                series[dt] = v
        return series

    def to_observations(
        self,
        district: str,
        start: date,
        end: date,
        zone_id: str,
        seed: Optional[int] = None,
    ) -> list[Observation]:
        """Hourly rainfall observations for ``district`` over [start, end].

        Each observation is tagged ``source_kind="disaggregated"`` and attached
        to ``zone_id`` with system ``"rainfall"``.
        """
        s = seed if seed is not None else self.seed
        observations: list[Observation] = []
        day_seed = s
        for row in self.daily_for_district(district, start, end):
            hourly = self.disaggregate_daily(row.rainfall, day_seed)
            day_seed += 1
            for hh, v in enumerate(hourly):
                if v <= 0:
                    continue  # skip dry hours to keep the stream sparse
                event_time = datetime(
                    row.date.year, row.date.month, row.date.day, hh, tzinfo=timezone.utc
                )
                observations.append(
                    Observation(
                        source="imd_rain",
                        source_kind=SourceKind.DISAGGREGATED,
                        zone=zone_id,
                        system="rainfall",
                        value=round(float(v), 4),
                        event_time=event_time,
                        arrival_time=event_time + timedelta(hours=1.0),
                        quality_flags=[],
                        node_id=f"{zone_id}:rainfall",
                    )
                )
        return observations

    # ----------------------------------------------------------------- presets
    def preset(self, name: str) -> dict:
        """Return a preset config dict (districts, start, end, label)."""
        if name not in PRESETS:
            raise ValueError(f"unknown preset {name!r}; options: {sorted(PRESETS)}")
        p = PRESETS[name]
        return {
            "name": name,
            "label": p["label"],
            "districts": list(p["districts"]),
            "start": datetime.strptime(p["start"], "%Y-%m-%d").date(),
            "end": datetime.strptime(p["end"], "%Y-%m-%d").date(),
        }

    def verify_presets(self) -> list[str]:
        """Verify each preset's documented extremes against the CSV.

        Returns a list of human-readable result lines. Prints them too.
        """
        self._require_loaded()
        lines: list[str] = []
        for name, p in PRESETS.items():
            lines.append(f"=== Preset {name}: {p['label']} ===")
            for district, check_date, expected_mm in p["check"]:
                row = next(
                    (
                        r
                        for r in self._district_rows(district)
                        if r.date == check_date
                    ),
                    None,
                )
                if row is None:
                    lines.append(
                        f"  {district} {check_date}: NOT FOUND in CSV "
                        f"(expected ~{expected_mm} mm)"
                    )
                    continue
                actual = row.rainfall
                ok = abs(actual - expected_mm) < 1.0
                status = "MATCH" if ok else "ADJUST"
                lines.append(
                    f"  {district} {check_date}: CSV={actual:.1f} mm, "
                    f"expected ~{expected_mm:.1f} mm -> {status}"
                )
                if not ok:
                    lines.append(
                        f"    -> preset/check value for {district} does not match "
                        f"the CSV; adjust PRESETS[{name!r}] 'check' entry."
                    )
        out = "\n".join(lines)
        print(out)
        return lines


def _opt_float(value) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None
