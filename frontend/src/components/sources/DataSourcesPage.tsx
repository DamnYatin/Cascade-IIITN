import React, { useMemo } from 'react';
import { Database } from 'lucide-react';
import { Card } from '../ui/Card';
import { SectionHeading } from '../ui/SectionHeading';
import { useStream } from '../../context/StreamContext';
import { SourceKind } from '../../types/api';
import { formatDuration, formatLocalTime, getLatencyMinutes, SOURCE_KIND_CONFIG } from '../../lib/formatters';

export const DataSourcesPage: React.FC = () => {
  const { observations } = useStream();

  // Aggregate stats from streaming observations by source
  const sourceStats = useMemo(() => {
    const map = new Map<
      string,
      {
        count: number;
        lastObserved: string | null;
        avgLatencyMin: number;
        sourceKind: string;
        system: string;
      }
    >();

    observations.forEach((obs) => {
      const existing = map.get(obs.source);
      const lat = getLatencyMinutes(obs.event_time, obs.arrival_time);
      if (!existing) {
        map.set(obs.source, {
          count: 1,
          lastObserved: obs.arrival_time,
          avgLatencyMin: lat,
          sourceKind: obs.source_kind,
          system: obs.system,
        });
      } else {
        existing.count++;
        existing.avgLatencyMin = Math.round((existing.avgLatencyMin + lat) / 2);
        if (new Date(obs.arrival_time) > new Date(existing.lastObserved || 0)) {
          existing.lastObserved = obs.arrival_time;
        }
      }
    });

    return map;
  }, [observations]);

  // Known repository adapters
  const knownAdapters = [
    {
      id: 'openmeteo',
      name: 'Open-Meteo ECMWF Ensemble',
      type: 'Real Rain & Weather',
      cadence: '1 hour',
      status: 'Active (Hero Replay Stream)',
      disclosure: 'Real historical ECMWF IFS / ERA5 high-resolution reanalysis cached for Upper Assam July-August 2026 window.',
    },
    {
      id: 'cwc',
      name: 'Central Water Commission (CWC)',
      type: 'River Gauge Levels',
      cadence: '3 hours',
      status: 'Not exposed by the API',
      disclosure: 'Hydrological gauge station adapter in backend/app/adapters/cwc.py. Direct live health endpoint not exposed by the API.',
    },
    {
      id: 'imerg',
      name: 'NASA GPM IMERG Gridded Rain',
      type: 'Satellite Precipitation',
      cadence: '30 mins',
      status: 'Not exposed by the API',
      disclosure: 'Satellite gridded precipitation adapter in backend/app/adapters/imerg.py. Direct live health endpoint not exposed by the API.',
    },
    {
      id: 'era5_land',
      name: 'ERA5-Land Soil & Runoff',
      type: 'Soil Saturation',
      cadence: '1 hour',
      status: 'Not exposed by the API',
      disclosure: 'Soil moisture and surface runoff adapter. Direct live health endpoint not exposed by the API.',
    },
    {
      id: 'imd',
      name: 'IMD Gridded Rainfall',
      type: 'District Observations',
      cadence: '24 hours',
      status: 'Not exposed by the API',
      disclosure: 'Daily rainfall totals disaggregated temporally into hourly pulses for storm simulation. Direct live health endpoint not exposed by the API.',
    },
  ];

  return (
    <div className="space-y-6">
      <SectionHeading
        title="Telemetry Feeds & Data Source Registry"
        subtitle="Catalog of physical, satellite, municipal, and synthetic data sources with provenance guarantees"
        icon={<Database size={18} className="text-text-primary" />}
      />

      {/* Ingested Feeds from Active Stream */}
      <Card variant="cream" className="p-5">
        <div className="flex items-center justify-between pb-3 border-b border-border mb-4">
          <div>
            <h3 className="font-heading text-base font-bold text-text-primary">
              Live Streaming Feeds (Active Session)
            </h3>
            <p className="text-xs text-text-muted mt-0.5">
              Derived from live observations arriving over /ws/stream
            </p>
          </div>
          <span className="text-xs font-mono font-bold text-navy bg-surface-muted px-2 py-0.5 rounded border border-border">
            {sourceStats.size} distinct sources detected
          </span>
        </div>

        {sourceStats.size > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="bg-[#eee9da] border-b border-border text-text-muted font-mono uppercase text-[11px]">
                  <th className="py-2.5 px-3">Source Identifier</th>
                  <th className="py-2.5 px-3">System Coupling</th>
                  <th className="py-2.5 px-3">Kind / Provenance</th>
                  <th className="py-2.5 px-3">Packet Count</th>
                  <th className="py-2.5 px-3">Avg Latency</th>
                  <th className="py-2.5 px-3">Last Arrival Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60 font-mono bg-white">
                {Array.from(sourceStats.entries()).map(([source, stats]) => {
                  const kindCfg =
                    SOURCE_KIND_CONFIG[stats.sourceKind as SourceKind] || SOURCE_KIND_CONFIG.simulated;
                  return (
                    <tr key={source} className="hover:bg-[#faf7ef]">
                      <td className="py-2.5 px-3 font-bold text-text-primary">{source}</td>
                      <td className="py-2.5 px-3 text-text-secondary uppercase">
                        {stats.system}
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`text-[9px] px-2 py-0.5 rounded border font-semibold ${kindCfg.bgClass} ${kindCfg.textClass} ${kindCfg.borderClass}`}
                        >
                          {kindCfg.label}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-navy font-bold tabular-nums">
                        {stats.count}
                      </td>
                      <td className="py-2.5 px-3 text-text-secondary tabular-nums">
                        {formatDuration(stats.avgLatencyMin)}
                      </td>
                      <td className="py-2.5 px-3 text-text-muted tabular-nums">
                        {formatLocalTime(stats.lastObserved)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-text-muted text-center py-6 font-mono">
            Awaiting streaming observations from WebSocket to index source feeds...
          </p>
        )}
      </Card>

      {/* Backend Adapter Registry & Truth Disclosure */}
      <Card variant="cream" className="p-5">
        <div className="flex items-center justify-between pb-3 border-b border-border mb-4">
          <div>
            <h3 className="font-heading text-base font-bold text-text-primary">
              Repository Adapters & Ingestion Modules
            </h3>
            <p className="text-xs text-text-muted mt-0.5">
              Verified backend adapter implementations in backend/app/adapters/
            </p>
          </div>
          <span className="text-xs font-mono text-text-primary bg-surface-muted px-2 py-0.5 rounded border border-border font-bold">
            5 Registered Adapters
          </span>
        </div>

        <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4 w-full">
          {knownAdapters.map((adp) => (
            <div
              key={adp.id}
              className="p-4 rounded-xl bg-white border border-border flex flex-col justify-between space-y-3 min-w-0"
            >
              <div className="min-w-0">
                <div className="flex items-start justify-between gap-2 min-w-0">
                  <h4 className="font-bold text-sm text-text-primary break-words [overflow-wrap:anywhere] min-w-0 flex-1">{adp.name}</h4>
                  <span
                    className={`text-[10px] font-mono px-1.5 py-0.5 rounded border font-bold shrink-0 ${
                      adp.id === 'openmeteo'
                        ? 'bg-risk-normal/15 text-risk-normal border-risk-normal/40'
                        : 'bg-surface-muted text-text-muted border-border'
                    }`}
                  >
                    {adp.status}
                  </span>
                </div>
                <p className="text-xs font-mono font-semibold text-navy mt-0.5">{adp.type}</p>
                <p className="text-xs text-text-secondary mt-2 leading-relaxed">
                  {adp.disclosure}
                </p>
              </div>

              <div className="pt-2 border-t border-border/60 text-[11px] font-mono text-text-muted flex justify-between">
                <span>Cadence: {adp.cadence}</span>
                <span className="text-text-secondary">adapters/{adp.id}.py</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};
