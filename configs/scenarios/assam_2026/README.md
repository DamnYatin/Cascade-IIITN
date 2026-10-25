# Assam Floods 2026 Scenario Package

## Provenance and Authority
All real-world event facts in this directory are parsed strictly from:
`docs/sources/Assam_Floods_2026_Report.md` (Compiled 25 October 2026).

Every record in `events.json`, `critical_labels.json`, `observed_response.json`, and `official_bulletins.json` carries:
1. `source_tags`: Clickable references matching `[S#]` tags defined in Section 12 of the report.
2. `reliability`: Graded A to D per Section 12 criteria:
   - **Grade A**: Wire/agency (PTI, ANI, IANS, AP) or established national/regional newspaper or official government release.
   - **Grade B**: NGO/humanitarian situation reports (ChildFund, ACT Alliance, SPHERE, NEADS).
   - **Grade C**: Opinion/editorial analysis (e.g. NorthEast Now EWS analysis [S24]).
   - **Grade D**: Aggregators or AI-assisted articles (lower confidence, never used for headline claims).

## Caveats and Interpretation Rules (from Report Section 1)
- **"Recent flood" means July–August 2026 Upper Assam floods**, originating from extreme rainfall in the Nagaland hills on 18–19 July 2026 and discharging into the Brahmaputra south-bank tributaries (Dikhow, Disang, Dhansiri).
- **Counts are point-in-time snapshots**, not cumulative totals. Numbers from daily ASDMA bulletins fluctuate as water rises and recedes.
- **Bulletin date vs publication date**: Wire reports often publish figures from the previous evening's bulletin.
- **Preservation of Discrepancies**: Where sources differ (e.g. crop area on 9 August: 11,933.46 ha vs ~119,000 ha; death toll around 21–23 July: 31 vs 41), both records are retained under a shared `conflict_group`. No silent reconciliation is performed.
- **Time Precision**: All timestamps are converted from IST (UTC+05:30) to UTC at the ingestion boundary. Events without explicit hours carry `time_precision: "day"` and span the entire 24-hour IST interval in UTC (`[YYYY-MM-(DD-1)T18:30:00Z, YYYY-MM-DDT18:30:00Z]`). Naive datetimes are strictly rejected.
- **Scope and Zone Attribution**: Impacts with unstated district locations (e.g. power cutoff to 1.26 lakh families on 20 July) are tagged `scope: "statewide_or_unspecified"` and `zone: null`. Highway inundation on NH-37 near Teok is tagged `zone: "jorhat"` with `zone_assignment: "inferred"`.

## File Contents
- `windows.yaml`: Named UTC evaluation windows (warmup, lead, onset, peak, recession, hero_full).
- `events.json`: Curated timeline of physical impacts, casualties, infrastructure damage, and response actions.
- `critical_labels.json`: Real-node coarse ground-truth CRITICAL/HIGH-RISK intervals for validation.
- `observed_response.json`: Timeline of actual government and community response, establishing the counterfactual baseline for Phase 2 early warning interventions.
- `official_bulletins.json`: ASDMA daily snapshot numbers recorded as observation-compatible event records.
