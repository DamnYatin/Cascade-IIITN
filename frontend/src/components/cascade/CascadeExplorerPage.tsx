import React, { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Network,
  ArrowRight,
  Layers,
} from 'lucide-react';
import { Card } from '../ui/Card';
import { RiskBadge } from '../ui/RiskBadge';
import { SectionHeading } from '../ui/SectionHeading';
import { useStream } from '../../context/StreamContext';
import { CityConfigResponse, ForecastSnapshot, RiskState, TopEdge } from '../../types/api';
import { formatPercent, RISK_STATE_CONFIG } from '../../lib/formatters';

/**
 * Break long snake_case identifiers naturally at word boundaries
 * by inserting a zero-width break opportunity (<wbr>) after underscores.
 */
function renderIdentifierWithBreaks(text: string | null | undefined) {
  if (!text) return text;
  const parts = text.split('_');
  return parts.map((part, index) => (
    <React.Fragment key={index}>
      {part}
      {index < parts.length - 1 && (
        <>
          _<wbr />
        </>
      )}
    </React.Fragment>
  ));
}

export const CascadeExplorerPage: React.FC = () => {
  const { currentConfig, latestForecast } = useStream();
  const [searchParams] = useSearchParams();
  const zoneParam = searchParams.get('zone');

  const [viewMode, setViewMode] = useState<'network' | 'geo'>('network');
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<TopEdge | null>(null);
  const [geoData, setGeoData] = useState<any>(null);
  const [systemFilter, setSystemFilter] = useState<string>('all');

  // Load geojson for Upper Assam
  useEffect(() => {
    fetch('/geo/upper_assam.geojson')
      .then((res) => {
        if (!res.ok) throw new Error('GeoJSON not found');
        return res.json();
      })
      .then((data) => setGeoData(data))
      .catch(() => {
        setGeoData(null);
      });
  }, []);

  // Set selected zone from URL query param if present, or default to first configured zone
  useEffect(() => {
    if (zoneParam && currentConfig?.zones.some((z) => z.id === zoneParam)) {
      setSelectedZoneId(zoneParam);
    } else if (!selectedZoneId && currentConfig?.zones.length) {
      setSelectedZoneId(currentConfig.zones[0].id);
    }
  }, [zoneParam, currentConfig, selectedZoneId]);

  // Edges from forecast top_edges or domain_prior_edges if available
  const edges: TopEdge[] = useMemo(() => {
    if (latestForecast?.top_edges && latestForecast.top_edges.length > 0) {
      return latestForecast.top_edges;
    }
    return [];
  }, [latestForecast]);

  // Selected zone object
  const selectedZone = useMemo(() => {
    return currentConfig?.zones.find((z) => z.id === selectedZoneId) || null;
  }, [currentConfig, selectedZoneId]);

  // Cascade stages involving selected zone or node
  const relevantStages = useMemo(() => {
    if (!latestForecast?.cascade_summary) return [];
    if (!selectedZoneId) return latestForecast.cascade_summary;
    return latestForecast.cascade_summary.filter((stg) => {
      return stg.node.startsWith(`${selectedZoneId}:`) || stg.dominant_parent?.startsWith(`${selectedZoneId}:`);
    });
  }, [latestForecast, selectedZoneId]);

  // Calculate SVG bounds for GeoJSON map
  const mapProjection = useMemo(() => {
    if (!geoData || !geoData.features) return null;
    let minLon = Infinity,
      maxLon = -Infinity,
      minLat = Infinity,
      maxLat = -Infinity;

    geoData.features.forEach((feat: any) => {
      const coords = feat.geometry?.coordinates;
      const processRing = (ring: any[]) => {
        ring.forEach(([lon, lat]: [number, number]) => {
          if (lon < minLon) minLon = lon;
          if (lon > maxLon) maxLon = lon;
          if (lat < minLat) minLat = lat;
          if (lat > maxLat) maxLat = lat;
        });
      };

      if (feat.geometry?.type === 'Polygon') {
        coords.forEach(processRing);
      } else if (feat.geometry?.type === 'MultiPolygon') {
        coords.forEach((poly: any[]) => poly.forEach(processRing));
      }
    });

    const width = 640;
    const height = 440;
    const padding = 30;

    const project = (lon: number, lat: number) => {
      const x = padding + ((lon - minLon) / (maxLon - minLon)) * (width - 2 * padding);
      const y = height - (padding + ((lat - minLat) / (maxLat - minLat)) * (height - 2 * padding));
      return [x, y];
    };

    return { project, width, height };
  }, [geoData]);

  return (
    <div className="space-y-6">
      {/* View Switcher & Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <SectionHeading
          title="Cascade & Stress Propagation Explorer"
          subtitle="Visualize multi-system couplings, learned dependencies, and spatial stress propagation"
          icon={<Network size={18} className="text-text-primary" />}
          className="mb-0"
        />

        <div className="flex items-center gap-2 self-start sm:self-center">
          <div className="flex bg-surface-muted p-1 rounded-lg border border-border">
            <button
              type="button"
              onClick={() => setViewMode('network')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                viewMode === 'network'
                  ? 'bg-white text-text-primary border border-border shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              System Network
            </button>
            <button
              type="button"
              onClick={() => setViewMode('geo')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                viewMode === 'geo'
                  ? 'bg-white text-text-primary border border-border shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              Spatial Map (GeoJSON)
            </button>
          </div>
        </div>
      </div>

      {/* Main Explorer Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Visualizer Panel (Network Graph or SVG Map) */}
        <Card variant="cream" className="lg:col-span-2 p-5 min-h-[520px] flex flex-col justify-between">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono uppercase text-text-muted font-semibold">
                {viewMode === 'network' ? 'TOPOLOGICAL DEPENDENCY GRAPH' : 'GEOJSON ZONE BOUNDARIES'}
              </span>
              <span className="text-[11px] font-mono text-text-primary bg-surface-muted px-2 py-0.5 rounded border border-border font-bold">
                {edges.length > 0 ? `${edges.length} Discovered Edges` : 'Configured Topology'}
              </span>
            </div>

            {/* System Filter for Network */}
            {viewMode === 'network' && (
              <select
                aria-label="Filter systems"
                value={systemFilter}
                onChange={(e) => setSystemFilter(e.target.value)}
                className="bg-white text-xs px-2.5 py-1 rounded border border-border text-text-primary focus:outline-none"
              >
                <option value="all">All Systems</option>
                {currentConfig?.systems.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.id.toUpperCase()}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Visualization Canvas */}
          <div className="relative flex-1 flex items-center justify-center py-4 overflow-hidden">
            {viewMode === 'geo' && mapProjection && geoData ? (
              <svg
                viewBox={`0 0 ${mapProjection.width} ${mapProjection.height}`}
                className="w-full h-auto max-h-[460px]"
              >
                {/* Render Polygons */}
                {geoData.features.map((feat: any) => {
                  const zoneId = feat.properties?.id;
                  const zoneName = feat.properties?.name || zoneId;
                  const isSelected = selectedZoneId === zoneId;
                  const rawRisk = latestForecast?.zone_risk_states?.[zoneId];
                  const zoneRisk: RiskState | null = rawRisk && rawRisk in RISK_STATE_CONFIG ? rawRisk : null;
                  const colorHex = zoneRisk ? RISK_STATE_CONFIG[zoneRisk].colorHex : '#c9c1ab';

                  // Build SVG path
                  const coords = feat.geometry?.coordinates;
                  let pathD = '';
                  const buildRingPath = (ring: any[]) => {
                    return ring
                      .map(([lon, lat], idx) => {
                        const [px, py] = mapProjection.project(lon, lat);
                        return `${idx === 0 ? 'M' : 'L'} ${px.toFixed(1)} ${py.toFixed(1)}`;
                      })
                      .join(' ') + ' Z';
                  };

                  if (feat.geometry?.type === 'Polygon') {
                    pathD = coords.map(buildRingPath).join(' ');
                  } else if (feat.geometry?.type === 'MultiPolygon') {
                    pathD = coords.map((p: any[]) => p.map(buildRingPath).join(' ')).join(' ');
                  }

                  // Centroid coordinates
                  const centroid = feat.properties?.centroid;
                  const [cx, cy] = centroid
                    ? mapProjection.project(centroid[0], centroid[1])
                    : [0, 0];

                  return (
                    <g key={zoneId} onClick={() => setSelectedZoneId(zoneId)} className="cursor-pointer group">
                      <path
                        d={pathD}
                        fill={isSelected ? '#f4c52f55' : `${colorHex}25`}
                        stroke={isSelected ? '#10224a' : colorHex}
                        strokeWidth={isSelected ? 2.5 : 1.2}
                        className="transition-all duration-200 group-hover:fill-accent-gold/40"
                      />
                      {centroid && (
                        <>
                          <circle
                            cx={cx}
                            cy={cy}
                            r={isSelected ? 5 : 3.5}
                            fill={colorHex}
                            stroke="#ffffff"
                            strokeWidth="1"
                            className="transition-transform duration-150"
                          />
                          <text
                            x={cx}
                            y={cy - 8}
                            textAnchor="middle"
                            className="text-[10px] fill-text-primary font-mono font-bold pointer-events-none drop-shadow"
                          >
                            {zoneName}
                          </text>
                        </>
                      )}
                    </g>
                  );
                })}
              </svg>
            ) : (
              /* Network Graph View */
              <div className="w-full h-full flex flex-col justify-center">
                {/* Zone Pill Selector */}
                <div className="flex flex-wrap gap-1.5 justify-center mb-6">
                  {currentConfig?.zones.map((z) => {
                    const isSelected = selectedZoneId === z.id;
                    const rawRisk = latestForecast?.zone_risk_states?.[z.id];
                    const zoneRisk: RiskState | null = rawRisk && rawRisk in RISK_STATE_CONFIG ? rawRisk : null;
                    const pillColorHex = zoneRisk ? RISK_STATE_CONFIG[zoneRisk].colorHex : '#c9c1ab';
                    return (
                      <button
                        key={z.id}
                        type="button"
                        onClick={() => setSelectedZoneId(z.id)}
                        className={`text-xs px-2.5 py-1 rounded-md border font-mono transition-all flex items-center gap-1.5 ${
                          isSelected
                            ? 'bg-navy text-white border-navy font-bold shadow-sm'
                            : 'bg-white text-text-secondary border-border hover:text-text-primary'
                        }`}
                      >
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ backgroundColor: pillColorHex }}
                        />
                        <span>{z.name}</span>
                      </button>
                    );
                  })}
                </div>

                {/* Coupled Systems Grid for Selected Zone */}
                <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3 w-full">
                  {currentConfig?.systems
                    .filter((sys) => systemFilter === 'all' || sys.id === systemFilter)
                    .map((sys) => {
                      const nodeId = `${selectedZoneId}:${sys.id}`;
                      const isNodeSelected = selectedNode === nodeId;

                      // Check if any stage affects this node
                      const stage = latestForecast?.cascade_summary?.find((s) => s.node === nodeId);

                      return (
                        <div
                          key={sys.id}
                          onClick={() => {
                            setSelectedNode(nodeId);
                            setSelectedEdge(null);
                          }}
                          className={`p-3.5 rounded-lg border cursor-pointer transition-all flex flex-col justify-between min-w-0 ${
                            isNodeSelected
                              ? 'bg-white border-navy ring-2 ring-navy/20 shadow-sm'
                              : 'bg-white/85 border-border hover:border-navy'
                          }`}
                          title={`${sys.id} (${sys.unit})`}
                        >
                          <div className="min-w-0 space-y-1">
                            <div
                              className="text-xs font-mono font-bold text-text-primary uppercase tracking-tight break-words [overflow-wrap:anywhere] leading-snug"
                              title={sys.id}
                            >
                              {renderIdentifierWithBreaks(sys.id)}
                            </div>
                            <div
                              className="text-[11px] text-text-muted font-mono break-words [overflow-wrap:anywhere] leading-tight"
                              title={sys.unit}
                            >
                              {renderIdentifierWithBreaks(sys.unit)}
                            </div>
                          </div>

                          <div className="mt-3 pt-2.5 border-t border-border/50 flex items-center justify-between text-[11px] font-mono min-w-0">
                            <span className="text-text-muted">Cascading:</span>
                            {stage ? (
                              <span className="text-risk-high font-bold">
                                Stage #{stage.stage}
                              </span>
                            ) : (
                              <span className="text-risk-normal font-semibold">Stable</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                </div>

                {/* Discovered Dependency Edges List */}
                <div className="mt-8 border-t border-border pt-4">
                  <p className="text-xs font-mono uppercase text-text-muted mb-2.5 font-semibold">
                    Learned Cross-System Coupling Edges (L1 Regularized Sparse Online Model)
                  </p>
                  {edges.length > 0 ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {edges.slice(0, 6).map((edge, idx) => {
                        const isEdgeSelected = selectedEdge?.u === edge.u && selectedEdge?.v === edge.v;
                        return (
                          <div
                            key={idx}
                            onClick={() => {
                              setSelectedEdge(edge);
                              setSelectedNode(null);
                            }}
                            className={`p-2 rounded border text-xs font-mono flex items-center justify-between cursor-pointer transition-all ${
                              isEdgeSelected
                                ? 'bg-white border-navy text-text-primary font-bold shadow-sm'
                                : 'bg-white/70 border-border hover:border-navy text-text-secondary'
                            }`}
                          >
                            <div className="flex items-center gap-1.5 truncate">
                              <span className="font-bold text-navy">{edge.u}</span>
                              <ArrowRight size={12} className="text-text-muted shrink-0" />
                              <span className="font-bold text-text-primary">{edge.v}</span>
                            </div>
                            <div className="flex items-center gap-2 shrink-0 text-[11px]">
                              <span className="text-navy font-semibold">+{edge.lag_hours}h</span>
                              <span className="text-text-primary font-bold">
                                w={edge.weight.toFixed(2)}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-text-muted">
                      No live learned edges currently active. Displaying domain prior structure.
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* Details & Explanation Panel */}
        <div className="space-y-5">
          {/* Selected Zone Overview */}
          <Card variant="cream">
            <div className="flex items-center justify-between pb-3 border-b border-border">
              <div>
                <h3 className="font-heading text-lg font-bold text-text-primary">
                  {selectedZone?.name || selectedZoneId}
                </h3>
                <p className="text-xs font-mono text-text-muted">Zone ID: {selectedZoneId}</p>
              </div>
              {selectedZoneId && (
                <RiskBadge
                  state={latestForecast?.zone_risk_states?.[selectedZoneId] || null}
                  size="md"
                />
              )}
            </div>

            <div className="mt-4 space-y-3 text-xs">
              <div className="flex justify-between">
                <span className="text-text-secondary">Jurisdiction / Role:</span>
                <span className="font-mono font-bold text-text-primary">
                  {selectedZone?.jurisdiction || selectedZone?.role || 'Assam Regional Zone'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Evidence Quality:</span>
                <span className="font-mono text-navy font-bold">
                  {selectedZoneId && latestForecast?.evidence_quality?.[selectedZoneId] !== undefined
                    ? formatPercent(latestForecast.evidence_quality[selectedZoneId])
                    : '100% (Nominal)'}
                </span>
              </div>
              <div>
                <span className="text-text-secondary block mb-1">Direct Neighbours:</span>
                <div className="flex flex-wrap gap-1">
                  {selectedZone?.neighbours && selectedZone.neighbours.length > 0 ? (
                    selectedZone.neighbours.map((nbr) => (
                      <button
                        key={nbr}
                        type="button"
                        onClick={() => setSelectedZoneId(nbr)}
                        className="text-[11px] font-mono px-2 py-0.5 rounded bg-white border border-border hover:border-navy text-text-secondary hover:text-text-primary transition-colors font-semibold"
                      >
                        {nbr}
                      </button>
                    ))
                  ) : (
                    <span className="text-text-muted">None specified</span>
                  )}
                </div>
              </div>
            </div>
          </Card>

          {/* Cascade Lineage / Stage Detail */}
          <Card variant="navy">
            <div className="flex items-center gap-2 mb-3 pb-2 border-b border-[#1e2c4f]">
              <Layers size={16} className="text-risk-watch" />
              <h4 className="font-heading text-sm font-bold text-white">
                Cascade Lineage & Drivers
              </h4>
            </div>

            {relevantStages.length > 0 ? (
              <div className="space-y-2.5">
                {relevantStages.map((stg) => (
                  <div
                    key={`${stg.stage}-${stg.node}`}
                    className="p-2.5 rounded-lg bg-navy-card border border-[#1e2c4f] text-xs font-mono"
                  >
                    <div className="flex items-start justify-between gap-2 min-w-0">
                      <span className="font-bold text-white break-words [overflow-wrap:anywhere] min-w-0" title={stg.node}>
                        {renderIdentifierWithBreaks(stg.node)}
                      </span>
                      <span className="text-accent-gold font-bold shrink-0">
                        P = {formatPercent(stg.probability)}
                      </span>
                    </div>

                    <div className="mt-1 text-[11px] text-text-navy-muted space-y-0.5">
                      <p>
                        Parent:{' '}
                        <span className="text-risk-watch font-semibold">
                          {stg.dominant_parent || 'Direct precipitation shock'}
                        </span>
                      </p>
                      <p>
                        ETA Interval:{' '}
                        <span className="text-white font-medium">
                          {stg.eta_p10 !== null && stg.eta_p90 !== null
                            ? `+${stg.eta_p10?.toFixed(1)}h – +${stg.eta_p90?.toFixed(1)}h`
                            : '—'}
                        </span>
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-navy-muted py-4 text-center">
                No active cascade propagation stages affecting {selectedZone?.name || selectedZoneId}.
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
};
