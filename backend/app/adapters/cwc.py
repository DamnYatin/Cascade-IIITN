"""Central Water Commission (CWC) river-level CSV drop-in adapter.

Reads manual drop-in files from data/raw/cwc/<station>.csv with columns:
  timestamp_ist,level_m,warning_level_m,danger_level_m,hfl_m

Converts IST (UTC+05:30) to UTC in code, validates columns, strictly rejects
naive times and non-numeric values, and applies latency gating.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..schemas import Observation, QualityFlag, SourceKind

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CWC_DIR = REPO_ROOT / "data" / "raw" / "cwc"
IST_TZ = timezone(timedelta(hours=5, minutes=30))
REQUIRED_CWC_COLUMNS = {"timestamp_ist", "level_m", "warning_level_m", "danger_level_m", "hfl_m"}


class CWCAdapter:
    """CWC river-level contract parser."""

    source_id = "river_stage_real"

    def __init__(
        self,
        cwc_dir: Path | str = DEFAULT_CWC_DIR,
        latency_hours: float = 1.0,
    ):
        self.cwc_dir = Path(cwc_dir)
        self.latency_hours = latency_hours

    def load_station(self, station_csv: Path | str, zone_id: str) -> list[Observation]:
        path = Path(station_csv)
        if not path.exists():
            raise FileNotFoundError(f"CWC station file not found: {path}")

        observations: list[Observation] = []
        with path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_CWC_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"CWC CSV {path.name} missing required columns: {sorted(missing)}"
                )

            for line_idx, row in enumerate(reader, start=2):
                ts_str = (row.get("timestamp_ist") or "").strip()
                if not ts_str:
                    continue

                # Parse timestamp and convert IST -> UTC
                try:
                    # Support ISO or '%Y-%m-%d %H:%M:%S'
                    if "T" in ts_str:
                        dt_raw = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    else:
                        dt_raw = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")

                    if dt_raw.tzinfo is None:
                        # Stated as timestamp_ist, localize to IST then convert to UTC
                        dt_ist = dt_raw.replace(tzinfo=IST_TZ)
                        dt_utc = dt_ist.astimezone(timezone.utc)
                    else:
                        dt_utc = dt_raw.astimezone(timezone.utc)

                    level_val = float(row["level_m"])
                    danger_val = float(row.get("danger_level_m", 0.0) or 0.0)
                except (ValueError, TypeError, KeyError) as exc:
                    raise ValueError(
                        f"CWC CSV {path.name} malformed at line {line_idx}: {exc}"
                    ) from exc

                arrival_time = dt_utc + timedelta(hours=self.latency_hours)
                flags = [QualityFlag.REAL, f"station={path.stem}"]
                if danger_val > 0 and level_val >= danger_val:
                    flags.append("above_danger_level")

                obs = Observation(
                    obs_id=f"cwc:{path.stem}:{dt_utc.strftime('%Y%m%d%H%M')}",
                    source=self.source_id,
                    source_kind=SourceKind.REAL,
                    zone=zone_id,
                    system="river_embankment",
                    value=round(level_val, 3),
                    event_time=dt_utc,
                    arrival_time=arrival_time,
                    quality_flags=flags,
                    node_id=f"{zone_id}:river_embankment",
                )
                observations.append(obs)

        return observations
