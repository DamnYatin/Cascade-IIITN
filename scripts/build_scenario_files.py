"""Generate scenario truth files from docs/sources/Assam_Floods_2026_Report.md.

Produces:
  - configs/scenarios/assam_2026/events.json
  - configs/scenarios/assam_2026/critical_labels.json
  - configs/scenarios/assam_2026/observed_response.json
  - configs/scenarios/assam_2026/official_bulletins.json

All times are converted from IST (UTC+05:30) to UTC at the edge.
Date-only events carry time_precision="day" and span the full IST 24h interval in UTC.
Preserves conflicts side-by-side with conflict_group.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "configs" / "scenarios" / "assam_2026"
IST = timezone(timedelta(hours=5, minutes=30))


def ist_day_interval_utc(d_str: str) -> list[str]:
    """Convert IST date YYYY-MM-DD to [start_utc, end_utc] covering full IST day."""
    d = datetime.strptime(d_str, "%Y-%m-%d").date()
    # 00:00:00 IST on d = (d - 1 day) at 18:30:00 UTC
    start_dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    end_dt = start_dt + timedelta(days=1)
    return [start_dt.isoformat().replace("+00:00", "Z"), end_dt.isoformat().replace("+00:00", "Z")]


def ist_time_interval_utc(d_str: str, t_str: str, span_minutes: int = 60) -> list[str]:
    """Convert specific IST timestamp to UTC interval."""
    d = datetime.strptime(d_str, "%Y-%m-%d").date()
    parts = [int(p) for p in t_str.split(":")]
    hh = parts[0]
    mm = parts[1] if len(parts) > 1 else 0
    center_dt = datetime(d.year, d.month, d.day, hh, mm, 0, tzinfo=IST).astimezone(timezone.utc)
    start_dt = center_dt - timedelta(minutes=span_minutes // 2)
    end_dt = center_dt + timedelta(minutes=span_minutes // 2)
    return [start_dt.isoformat().replace("+00:00", "Z"), end_dt.isoformat().replace("+00:00", "Z")]


def build_events() -> list[dict[str, Any]]:
    events = [
        # 18-20 July Rain
        {
            "id": "ev_20260718_upstream_rain",
            "date_ist": "2026-07-18",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": [
                ist_day_interval_utc("2026-07-18")[0],
                ist_day_interval_utc("2026-07-20")[1],
            ],
            "zone": "mon_nl",
            "scope": "multi_zone",
            "system": "river_embankment",
            "kind": "cause",
            "claim": "Very heavy rain over Upper Assam and Nagaland catchments (Mon, Mokokchung, Wokha); Dikhow, Disang, Dhansiri swell.",
            "value": 137.0,
            "unit": "mm_accumulated",
            "source_tags": ["S1", "S24", "S26"],
            "reliability": "A",
            "headline": False,
            "conflict_group": "cloudburst_cause",
            "zone_assignment": "stated",
            "notes": "Aboi AWS recorded 137 mm over 8-9h; Charaideo recorded 170 mm (~436% above seasonal average).",
        },
        # 19 July Santak water entry
        {
            "id": "ev_20260719_santak_entry",
            "date_ist": "2026-07-19",
            "time_ist": "13:00",
            "time_precision": "approx",
            "interval_utc": ist_time_interval_utc("2026-07-19", "13:00", span_minutes=60),
            "zone": "sivasagar",
            "scope": "zone",
            "system": "river_embankment",
            "kind": "impact",
            "claim": "Santak Panchali water entered at about 1 pm and reached chest height within 20 minutes.",
            "value": None,
            "unit": None,
            "source_tags": ["S1"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Surge arrived rapidly from Naga hills in roughly 90 minutes.",
        },
        # 19 July Betbari Submerged (~19:30 IST = 14:00Z)
        {
            "id": "ev_20260719_betbari_submerged",
            "date_ist": "2026-07-19",
            "time_ist": "19:30",
            "time_precision": "approx",
            "interval_utc": ist_time_interval_utc("2026-07-19", "19:30", span_minutes=60),
            "zone": "sivasagar",
            "scope": "zone",
            "system": "river_embankment",
            "kind": "impact",
            "claim": "Betbari village fully submerged around 7:30 pm on 19 July; water from Dikhow flowed into Dorika; 99% houses affected.",
            "value": 99.0,
            "unit": "percent_houses",
            "source_tags": ["S1"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Calculated UTC: 19:30 IST - 05:30 = 14:00:00Z.",
        },
        # 19 July Midnight Nepalikhuti Rooftops
        {
            "id": "ev_20260719_nepalikhuti_midnight",
            "date_ist": "2026-07-19",
            "time_ist": "23:59",
            "time_precision": "approx",
            "interval_utc": [
                "2026-07-19T17:00:00Z",  # covering start/end of midnight IST window
                "2026-07-19T20:00:00Z",
            ],
            "zone": "sivasagar",
            "scope": "zone",
            "system": "human_toll",
            "kind": "impact",
            "claim": "Nepalikhuti (Sivasagar) residents climb onto rooftops as water rushes in around midnight; 60-65 families shelter in 2-storey building.",
            "value": 65.0,
            "unit": "families_sheltered",
            "source_tags": ["S1"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Window covers both start of night and midnight IST.",
        },
        # 20 July Simaluguri Railway Flooding
        {
            "id": "ev_20260720_simaluguri_railway",
            "date_ist": "2026-07-20",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-20"),
            "zone": "sivasagar",
            "scope": "zone",
            "system": "transport",
            "kind": "impact",
            "claim": "Dikhow floods Simaluguri railway station yard, colony and tracks; long-distance trains diverted via Rangiya, local trains suspended.",
            "value": None,
            "unit": None,
            "source_tags": ["S14", "S21", "S49"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Named services affected include Rajdhani, Vivek Express, Kamrup Express.",
        },
        # 20 July NH-37 (NH-715) Submerged near Teok
        {
            "id": "ev_20260720_nh37_teok",
            "date_ist": "2026-07-20",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-20"),
            "zone": "jorhat",
            "scope": "zone",
            "system": "transport",
            "kind": "impact",
            "claim": "A key stretch of NH-37 (now NH-715) near Teok submerged; traffic near standstill; travel advisory issued.",
            "value": None,
            "unit": None,
            "source_tags": ["S14"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "inferred",
            "notes": "Teok revenue circle is in Jorhat district (inferred from OSM).",
        },
        # 20 July Power cut to 1.26 lakh families
        {
            "id": "ev_20260720_power_cut_deluge",
            "date_ist": "2026-07-20",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-20"),
            "zone": None,
            "scope": "statewide_or_unspecified",
            "system": "power",
            "kind": "impact",
            "claim": "Power supply to 1.26 lakh families disconnected during the deluge.",
            "value": 126000.0,
            "unit": "families_disconnected",
            "source_tags": ["S37"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "CM stated statewide total; district not specified, so no single zone assigned.",
        },
        # 20 July Dikhow Highest Flood Level (HFL) & Embankment Breaches
        {
            "id": "ev_20260720_dikhow_hfl_breaches",
            "date_ist": "2026-07-20",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-20"),
            "zone": "sivasagar",
            "scope": "multi_zone",
            "system": "river_embankment",
            "kind": "impact",
            "claim": "Dikhow crossed its highest flood level at Sivasagar; eight embankment breaches reported in Jorhat region.",
            "value": 8.0,
            "unit": "embankment_breaches",
            "source_tags": ["S13", "S14"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Dorika and Dikhow bunds breached.",
        },
        # 20 July Nazira Tea Estates Hospital Flooding
        {
            "id": "ev_20260720_nazira_tea_hospitals",
            "date_ist": "2026-07-20",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-20"),
            "zone": "sivasagar",
            "scope": "zone",
            "system": "health",
            "kind": "impact",
            "claim": "Estate hospitals in Nazira tea estates under floodwater; medical access severed.",
            "value": None,
            "unit": None,
            "source_tags": ["S29"],
            "reliability": "B",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Pregnant tea garden worker delivered inside factory due to flooded hospital.",
        },
        # 21 July Army joins NDRF / Relief camps
        {
            "id": "ev_20260721_army_ndrf_deployment",
            "date_ist": "2026-07-21",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-21"),
            "zone": None,
            "scope": "statewide",
            "system": "emergency_response",
            "kind": "response",
            "claim": "Army joins NDRF and SDRF; 101 relief camps opened sheltering 9,600+; 6,700+ rescued; toll reported at 10.",
            "value": 101.0,
            "unit": "relief_camps",
            "source_tags": ["S11", "S19", "S22"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "SDRF deployed 62 rescue boats.",
        },
        # 21-22 July Spike in deaths & conflict 31 vs 41
        {
            "id": "ev_20260722_toll_spike_31",
            "date_ist": "2026-07-22",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-22"),
            "zone": None,
            "scope": "statewide",
            "system": "human_toll",
            "kind": "impact",
            "claim": "21 deaths reported in a single day, taking toll to 31; 16 districts, 872 villages, 5.65 lakh affected, 24,210 ha cropland damaged.",
            "value": 31.0,
            "unit": "deaths_toll",
            "source_tags": ["S12", "S13", "S14"],
            "reliability": "A",
            "headline": True,
            "conflict_group": "toll_20260722",
            "zone_assignment": "stated",
            "notes": "Primary toll figure from established agencies (The Wire / LatestLY).",
        },
        {
            "id": "ev_20260722_toll_spike_41",
            "date_ist": "2026-07-22",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-22"),
            "zone": None,
            "scope": "statewide",
            "system": "human_toll",
            "kind": "impact",
            "claim": "Death toll reported at 41 after 10 deaths in one day.",
            "value": 41.0,
            "unit": "deaths_toll",
            "source_tags": ["S47"],
            "reliability": "D",
            "headline": False,
            "conflict_group": "toll_20260722",
            "zone_assignment": "stated",
            "notes": "Alternative aggregator figure preserved without silent reconciliation.",
        },
        # 25 July Peak Impact (7.05 lakh affected, toll 61)
        {
            "id": "ev_20260725_peak_impact",
            "date_ist": "2026-07-25",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-25"),
            "zone": None,
            "scope": "statewide",
            "system": "human_toll",
            "kind": "impact",
            "claim": "Peak of reported impact: 7.05 lakh affected across 12 districts, 856 villages, 56,606.78 ha submerged; toll 61 after 14 deaths in 24 hours.",
            "value": 705000.0,
            "unit": "people_affected",
            "source_tags": ["S15", "S23"],
            "reliability": "A",
            "headline": True,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Deaths breakdown: 7 Charaideo, 6 Sivasagar, 1 Jorhat.",
        },
        # 5-6 August Toll 95 & District Breakdown
        {
            "id": "ev_20260806_toll_95_districts",
            "date_ist": "2026-08-06",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-06"),
            "zone": None,
            "scope": "statewide",
            "system": "human_toll",
            "kind": "impact",
            "claim": "Toll reaches 95: Sivasagar 50, Charaideo 21, Jorhat 9, Golaghat 5, Dhemaji 3, Karbi Anglong 2, Biswanath 2, Sonitpur 1, Kamrup Metropolitan 1, Morigaon 1 (sum = 95).",
            "value": 95.0,
            "unit": "deaths_toll",
            "source_tags": ["S9", "S10"],
            "reliability": "A",
            "headline": True,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "District counts strictly sum to 95.",
        },
        # 9-10 August Toll 100 Anchor
        {
            "id": "ev_20260810_toll_100",
            "date_ist": "2026-08-10",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-10"),
            "zone": None,
            "scope": "statewide",
            "system": "human_toll",
            "kind": "impact",
            "claim": "Official death toll reaches 100 with two more deaths; 1,37,500 affected across seven districts.",
            "value": 100.0,
            "unit": "deaths_toll",
            "source_tags": ["S2", "S3", "S5"],
            "reliability": "A",
            "headline": True,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Major anchor verified across PTI and AP.",
        },
        # 9 August Crop Area Discrepancy (11,933.46 ha vs 119,000 ha)
        {
            "id": "ev_20260809_crop_area_pti",
            "date_ist": "2026-08-09",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-09"),
            "zone": None,
            "scope": "statewide",
            "system": "agriculture",
            "kind": "impact",
            "claim": "11,933.46 ha crop area damaged across seven districts.",
            "value": 11933.46,
            "unit": "hectares",
            "source_tags": ["S2"],
            "reliability": "A",
            "headline": False,
            "conflict_group": "crop_area_20260809",
            "zone_assignment": "stated",
            "notes": "Official PTI bulletin figure.",
        },
        {
            "id": "ev_20260809_crop_area_mongabay",
            "date_ist": "2026-08-09",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-09"),
            "zone": None,
            "scope": "statewide",
            "system": "agriculture",
            "kind": "impact",
            "claim": "About 119,000 ha agricultural land submerged in the 9 August bulletin.",
            "value": 119000.0,
            "unit": "hectares",
            "source_tags": ["S1"],
            "reliability": "A",
            "headline": False,
            "conflict_group": "crop_area_20260809",
            "zone_assignment": "stated",
            "notes": "Tenfold discrepancy in Mongabay reporting of the same bulletin retained.",
        },
        # 12-13 August Toll 103 Anchor
        {
            "id": "ev_20260813_toll_103",
            "date_ist": "2026-08-13",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-13"),
            "zone": None,
            "scope": "statewide",
            "system": "human_toll",
            "kind": "impact",
            "claim": "Death toll rises to 103 after two drownings in Sivasagar and Karbi Anglong; 86,800+ affected across four districts.",
            "value": 103.0,
            "unit": "deaths_toll",
            "source_tags": ["S6", "S7"],
            "reliability": "A",
            "headline": True,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Final recorded flood fatality milestone.",
        },
        # 14 August SDRF Central Advance
        {
            "id": "ev_20260814_sdrf_advance",
            "date_ist": "2026-08-14",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-14"),
            "zone": None,
            "scope": "statewide",
            "system": "emergency_response",
            "kind": "response",
            "claim": "Centre approves advance SDRF release: Rs 379.35 crore to Assam (part of Rs 2,117.85 crore for seven states).",
            "value": 379.35,
            "unit": "crore_inr",
            "source_tags": ["S35"],
            "reliability": "A",
            "headline": False,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Disaster relief advance sanctioned by Ministry of Home Affairs.",
        },
        # 17 August Damage Assessment (480 Cr & 26,681 houses)
        {
            "id": "ev_20260817_damage_assessment",
            "date_ist": "2026-08-17",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-17"),
            "zone": None,
            "scope": "statewide",
            "system": "housing",
            "kind": "impact",
            "claim": "CM: flood damage estimated at Rs 480 crore; 26,681 houses affected; 96,842 families paid Rs 15,000 interim relief.",
            "value": 480.0,
            "unit": "crore_inr",
            "source_tags": ["S36"],
            "reliability": "A",
            "headline": True,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "26,681 houses damaged across Upper Assam.",
        },
        # 1 September Relief Disbursed (175.64 Cr)
        {
            "id": "ev_20260901_relief_disbursed",
            "date_ist": "2026-09-01",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-09-01"),
            "zone": None,
            "scope": "statewide",
            "system": "emergency_response",
            "kind": "response",
            "claim": "Total relief disbursed reaches Rs 175.64 crore; Phase-IV releases Rs 25.12 crore; 1,182 teachers conclude rapid digital survey of 94,545 households.",
            "value": 175.64,
            "unit": "crore_inr",
            "source_tags": ["S37", "S38"],
            "reliability": "A",
            "headline": True,
            "conflict_group": None,
            "zone_assignment": "stated",
            "notes": "Fresh flooding at Gohpur on 30-31 Aug also recorded.",
        },
    ]
    return events


def build_critical_labels() -> list[dict[str, Any]]:
    """Coarse, honest CRITICAL / HIGH_RISK intervals for real nodes derived from reported impacts."""
    return [
        {
            "node_id": "sivasagar:river_embankment",
            "zone": "sivasagar",
            "system": "river_embankment",
            "state": "CRITICAL",
            "interval_utc": [
                "2026-07-19T13:30:00Z",  # Santak water ingress
                "2026-07-26T18:30:00Z",  # Peak floodwaters receding
            ],
            "time_precision": "hour",
            "label_confidence": 0.95,
            "source_tags": ["S1", "S14", "S21"],
            "anchor_rationale": "Dikhow crossed highest flood level at Sivasagar; Betbari and Santak fully submerged.",
        },
        {
            "node_id": "sivasagar:transport",
            "zone": "sivasagar",
            "system": "transport",
            "state": "CRITICAL",
            "interval_utc": [
                "2026-07-20T00:00:00Z",
                "2026-07-23T18:00:00Z",
            ],
            "time_precision": "day",
            "label_confidence": 0.95,
            "source_tags": ["S14", "S21", "S49"],
            "anchor_rationale": "Simaluguri station tracks, yard, and railway colony flooded; train services cancelled or diverted.",
        },
        {
            "node_id": "jorhat:river_embankment",
            "zone": "jorhat",
            "system": "river_embankment",
            "state": "CRITICAL",
            "interval_utc": [
                "2026-07-20T00:00:00Z",
                "2026-07-26T18:00:00Z",
            ],
            "time_precision": "day",
            "label_confidence": 0.90,
            "source_tags": ["S13", "S16"],
            "anchor_rationale": "Eight major embankment breaches in the Jorhat region; Selengahat inundated.",
        },
        {
            "node_id": "jorhat:transport",
            "zone": "jorhat",
            "system": "transport",
            "state": "HIGH_RISK",
            "interval_utc": [
                "2026-07-20T06:00:00Z",
                "2026-07-23T18:00:00Z",
            ],
            "time_precision": "approx",
            "label_confidence": 0.90,
            "source_tags": ["S14"],
            "anchor_rationale": "NH-37 (NH-715) submerged near Teok; traffic halted; advisory issued for Guwahati-Dibrugarh highway.",
        },
        {
            "node_id": "sivasagar:health",
            "zone": "sivasagar",
            "system": "health",
            "state": "CRITICAL",
            "interval_utc": [
                "2026-07-20T00:00:00Z",
                "2026-07-25T00:00:00Z",
            ],
            "time_precision": "day",
            "label_confidence": 0.85,
            "source_tags": ["S29"],
            "anchor_rationale": "Nazira tea-estate hospitals flooded; medical staff isolated; emergency childbirths in factory quarters.",
        },
        {
            "node_id": "charaideo:river_embankment",
            "zone": "charaideo",
            "system": "river_embankment",
            "state": "CRITICAL",
            "interval_utc": [
                "2026-07-19T14:00:00Z",
                "2026-07-26T18:00:00Z",
            ],
            "time_precision": "approx",
            "label_confidence": 0.90,
            "source_tags": ["S1", "S10", "S15"],
            "anchor_rationale": "Disang surge from Mon hills batters Charaideo (170 mm rain, 21 deaths, 8,300 ha crop lost).",
        },
        {
            "node_id": "golaghat:river_embankment",
            "zone": "golaghat",
            "system": "river_embankment",
            "state": "CRITICAL",
            "interval_utc": [
                "2026-07-21T00:00:00Z",
                "2026-08-07T18:00:00Z",
            ],
            "time_precision": "day",
            "label_confidence": 0.90,
            "source_tags": ["S9", "S10", "S12"],
            "anchor_rationale": "Dhansiri (South) above danger mark at Numaligarh; bridge collapse; 70,000 affected in August wave.",
        },
        {
            "node_id": "kamrup_metropolitan:river_embankment",
            "zone": "kamrup_metropolitan",
            "system": "river_embankment",
            "state": "HIGH_RISK",
            "interval_utc": [
                "2026-07-20T18:30:00Z",
                "2026-07-22T18:30:00Z",
            ],
            "time_precision": "day",
            "label_confidence": 0.85,
            "source_tags": ["S11", "S19", "S22"],
            "anchor_rationale": "Urban flooding hits Guwahati; North Guwahati wards 1, 4, 5, 6 flooded; 62 SDRF rescue boats deployed.",
        },
    ]


def build_observed_response() -> list[dict[str, Any]]:
    """Chronology of actual government and humanitarian response (counterfactual baseline)."""
    return [
        {
            "id": "resp_001_nagaland_alert",
            "date_ist": "2026-07-19",
            "time_ist": "10:00",
            "time_precision": "approx",
            "interval_utc": ist_time_interval_utc("2026-07-19", "10:00", span_minutes=30),
            "actor": "Nagaland State Authorities",
            "action": "Alert sent to Assam Chief Secretary within ~10 minutes of surge observation; no automated public alert reached downstream communities.",
            "source_tags": ["S24"],
            "reliability": "C",
            "counterfactual_relevance": "Key bottleneck: hydrograph reached plains in ~90 min, but public warning was absent.",
        },
        {
            "id": "resp_002_army_ndrf_deployment",
            "date_ist": "2026-07-20",
            "time_ist": "18:00",
            "time_precision": "approx",
            "interval_utc": ist_time_interval_utc("2026-07-20", "18:00", span_minutes=240),
            "actor": "Indian Army, NDRF, SDRF",
            "action": "Army deployed alongside NDRF in Sivasagar, Charaideo, Jorhat; SDRF deploys 62 boats; 6,700+ people evacuated.",
            "source_tags": ["S11", "S19", "S22"],
            "reliability": "A",
            "counterfactual_relevance": "Deployment was reactive to inundation rather than prepositioned 24-48h ahead.",
        },
        {
            "id": "resp_003_relief_camps_opened",
            "date_ist": "2026-07-21",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-21"),
            "actor": "ASDMA & District Administrations",
            "action": "101 relief camps and distribution centres established, sheltering 9,600+ flood-displaced citizens.",
            "source_tags": ["S11"],
            "reliability": "A",
            "counterfactual_relevance": "Camps surged after major village submergence occurred on 19-20 July.",
        },
        {
            "id": "resp_004_special_trains_rerouting",
            "date_ist": "2026-07-21",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-07-21"),
            "actor": "Northeast Frontier Railway (NFR)",
            "action": "Long-distance services rerouted via Rangiya-Rangapara; special shuttle trains and buses run for stranded passengers.",
            "source_tags": ["S14", "S19", "S20"],
            "reliability": "A",
            "counterfactual_relevance": "Tracks inundated before proactive diversions could take place.",
        },
        {
            "id": "resp_005_central_team_visit",
            "date_ist": "2026-07-26",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": [
                ist_day_interval_utc("2026-07-26")[0],
                ist_day_interval_utc("2026-07-29")[1],
            ],
            "actor": "Inter-Ministerial Central Team (IMCT)",
            "action": "Six-member central team reviews damage in Charaideo, Sivasagar, Jorhat, Golaghat; state requests relaxed SDRF norms.",
            "source_tags": ["S30"],
            "reliability": "A",
            "counterfactual_relevance": "Damage assessment occurred post-peak.",
        },
        {
            "id": "resp_006_interim_relief_announcement",
            "date_ist": "2026-08-03",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-03"),
            "actor": "Government of Assam",
            "action": "Announced Rs 15,000 interim assistance per family, power bill waiver up to 300 units in Sivasagar and Charaideo.",
            "source_tags": ["S1", "S41"],
            "reliability": "A",
            "counterfactual_relevance": "Relief announced 15 days after initial flood surge.",
        },
        {
            "id": "resp_007_sdrf_advance_sanction",
            "date_ist": "2026-08-14",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-08-14"),
            "actor": "Ministry of Home Affairs, Government of India",
            "action": "Approved advance SDRF release of Rs 379.35 crore to Assam.",
            "source_tags": ["S35"],
            "reliability": "A",
            "counterfactual_relevance": "Central emergency liquidity injection.",
        },
        {
            "id": "resp_008_digital_survey_phase4",
            "date_ist": "2026-09-01",
            "time_ist": None,
            "time_precision": "day",
            "interval_utc": ist_day_interval_utc("2026-09-01"),
            "actor": "Government of Assam",
            "action": "Phase-IV relief: Rs 25.12 crore disbursed; rapid digital damage survey of 94,545 households concluded by 1,182 teachers.",
            "source_tags": ["S37", "S38"],
            "reliability": "A",
            "counterfactual_relevance": "Final baseline snapshot of rapid digital rehabilitation assessment.",
        },
    ]


def build_official_bulletins() -> list[dict[str, Any]]:
    """Curated ASDMA official bulletin snapshots recorded as Observation-compatible records."""
    bulletins = [
        {
            "obs_id": "asdma:statewide:20260720",
            "source": "asdma_bulletin_via_report",
            "source_kind": "real",
            "zone": "sivasagar",
            "system": "human_toll",
            "value": 362933.0,
            "unit": "people_affected",
            "event_time": "2026-07-20T14:30:00Z",  # 20:00 IST bulletin time
            "arrival_time": "2026-07-20T16:30:00Z",
            "quality_flags": ["real", "source=asdma_snapshot", "reliability=A", "districts=16", "villages=794", "crop_ha=19100"],
            "node_id": "sivasagar:human_toll",
        },
        {
            "obs_id": "asdma:statewide:20260722",
            "source": "asdma_bulletin_via_report",
            "source_kind": "real",
            "zone": "sivasagar",
            "system": "human_toll",
            "value": 564660.0,
            "unit": "people_affected",
            "event_time": "2026-07-22T14:30:00Z",
            "arrival_time": "2026-07-22T16:30:00Z",
            "quality_flags": ["real", "source=asdma_snapshot", "reliability=A", "districts=16", "villages=872", "crop_ha=24210"],
            "node_id": "sivasagar:human_toll",
        },
        {
            "obs_id": "asdma:statewide:20260725",
            "source": "asdma_bulletin_via_report",
            "source_kind": "real",
            "zone": "sivasagar",
            "system": "human_toll",
            "value": 705000.0,
            "unit": "people_affected",
            "event_time": "2026-07-25T14:30:00Z",
            "arrival_time": "2026-07-25T16:30:00Z",
            "quality_flags": ["real", "source=asdma_snapshot", "reliability=A", "districts=12", "villages=856", "crop_ha=56606.78"],
            "node_id": "sivasagar:human_toll",
        },
        {
            "obs_id": "asdma:statewide:20260727",
            "source": "asdma_bulletin_via_report",
            "source_kind": "real",
            "zone": "sivasagar",
            "system": "human_toll",
            "value": 445385.0,
            "unit": "people_affected",
            "event_time": "2026-07-27T14:30:00Z",
            "arrival_time": "2026-07-27T16:30:00Z",
            "quality_flags": ["real", "source=asdma_snapshot", "reliability=A", "districts=6", "villages=631", "crop_ha=37139.52"],
            "node_id": "sivasagar:human_toll",
        },
        {
            "obs_id": "asdma:statewide:20260806",
            "source": "asdma_bulletin_via_report",
            "source_kind": "real",
            "zone": "sivasagar",
            "system": "human_toll",
            "value": 160653.0,
            "unit": "people_affected",
            "event_time": "2026-08-06T14:30:00Z",
            "arrival_time": "2026-08-06T16:30:00Z",
            "quality_flags": ["real", "source=asdma_snapshot", "reliability=A", "districts=14", "villages=563", "crop_ha=17000"],
            "node_id": "sivasagar:human_toll",
        },
        {
            "obs_id": "asdma:statewide:20260809",
            "source": "asdma_bulletin_via_report",
            "source_kind": "real",
            "zone": "sivasagar",
            "system": "human_toll",
            "value": 137500.0,
            "unit": "people_affected",
            "event_time": "2026-08-09T14:30:00Z",
            "arrival_time": "2026-08-09T16:30:00Z",
            "quality_flags": ["real", "source=asdma_snapshot", "reliability=A", "districts=7", "villages=456", "crop_ha=11933.46"],
            "node_id": "sivasagar:human_toll",
        },
    ]
    return bulletins


def main():
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)

    events = build_events()
    events_path = SCENARIOS_DIR / "events.json"
    with events_path.open("w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)
    print(f"Wrote {len(events)} curated events to {events_path}")

    critical = build_critical_labels()
    crit_path = SCENARIOS_DIR / "critical_labels.json"
    with crit_path.open("w", encoding="utf-8") as f:
        json.dump(critical, f, indent=2)
    print(f"Wrote {len(critical)} critical node labels to {crit_path}")

    observed = build_observed_response()
    obs_path = SCENARIOS_DIR / "observed_response.json"
    with obs_path.open("w", encoding="utf-8") as f:
        json.dump(observed, f, indent=2)
    print(f"Wrote {len(observed)} observed response records to {obs_path}")

    bulletins = build_official_bulletins()
    bull_path = SCENARIOS_DIR / "official_bulletins.json"
    with bull_path.open("w", encoding="utf-8") as f:
        json.dump(bulletins, f, indent=2)
    print(f"Wrote {len(bulletins)} official bulletin records to {bull_path}")


if __name__ == "__main__":
    main()
