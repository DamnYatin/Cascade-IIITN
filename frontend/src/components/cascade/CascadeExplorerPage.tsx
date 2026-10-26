import React, { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Network,
  Map as MapIcon,
  Layers,
  Filter,
} from 'lucide-react';
import { Card } from '../ui/Card';
import { SectionHeading } from '../ui/SectionHeading';
import { useStream } from '../../context/StreamContext';
import { TopEdge } from '../../types/api';
import {
  buildZoneAdjacency,
  buildSystemNodes,
  buildForecastEdges,
  buildCascadePath,
} from '../../lib/graphModel';
import { GraphCanvas } from './GraphCanvas';
import { CityStructurePanel } from './CityStructurePanel';
import { RISK_STATE_CONFIG } from '../../lib/formatters';

export const CascadeExplorerPage: React.FC = () => {
  const { currentConfig, latestForecast, connState, wsStatus } = useStream();
  const [searchParams] = useSearchParams();
  const zoneParam = searchParams.get('zone');

  const [viewMode, setViewMode] = useState<'network' | 'geo'>('network');
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<TopEdge | null>(null);
  const [systemFilter, setSystemFilter] = useState<string>('all');
  const [expandAllSystems, setExpandAllSystems] = useState<boolean>(false);

  // Layer toggles for the 4 distinct graph layers
  const [layerToggles, setLayerToggles] = useState({
    showAdjacency: true,
    showForecastEdges: true,
    showCascadePath: true,
    showEdgeChanges: true,
  });

  // GeoJSON data for Upper Assam map tab
  const [geoData, setGeoData] = useState<any>(null);

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

  // Update selected zone from URL query param if present
  useEffect(() => {
    if (zoneParam && currentConfig?.zones.some((z) => z.id === zoneParam)) {
      setSelectedZoneId(zoneParam);
    } else if (!selectedZoneId && currentConfig?.zones.length) {
      setSelectedZoneId(currentConfig.zones[0].id);
    }
  }, [zoneParam, currentConfig, selectedZoneId]);

  // Pure models
  const adjacency = useMemo(() => buildZoneAdjacency(currentConfig), [currentConfig]);
  const { validNodeIds } = useMemo(() => buildSystemNodes(currentConfig), [currentConfig]);

  const { edges: forecastEdges, unknownNodeRecordsCount } = useMemo(
    () => buildForecastEdges(latestForecast?.top_edges, validNodeIds),
    [latestForecast?.top_edges, validNodeIds]
  );

  const { stages: cascadeStages, unknownNodeStagesCount } = useMemo(
    () => buildCascadePath(latestForecast?.cascade_summary, forecastEdges, validNodeIds),
    [latestForecast?.cascade_summary, forecastEdges, validNodeIds]
  );

  // Map projection for GeoJSON tab
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

  const isStreamConnected = connState.wsConnection === 'connected' || wsStatus === 'open';

  return (
    <div className="space-y-5">
      {/* Page Heading & Main View Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <SectionHeading
          title="Cascade & Stress Propagation Explorer"
          subtitle="Explore configured city topology, online forecaster dependency couplings, and predicted cascade lineages"
          icon={<Network size={18} className="text-text-primary" />}
          className="mb-0"
        />

        <div className="flex items-center gap-2 self-start sm:self-center">
          <div className="flex bg-surface-muted p-1 rounded-lg border border-border">
            <button
              type="button"
              onClick={() => setViewMode('network')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center gap-1.5 ${
                viewMode === 'network'
                  ? 'bg-white text-text-primary border border-border shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Network size={14} />
              <span>System & Topology Graph</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode('geo')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center gap-1.5 ${
                viewMode === 'geo'
                  ? 'bg-white text-text-primary border border-border shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <MapIcon size={14} />
              <span>Spatial Map (GeoJSON)</span>
            </button>
          </div>
        </div>
      </div>

      {/* Layer Toggles and Filter Bar (shown in Network mode) */}
      {viewMode === 'network' && (
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg bg-white border border-border shadow-sm text-xs font-mono">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-text-muted uppercase text-[10px] font-bold flex items-center gap-1 mr-1">
              <Layers size={13} className="text-navy" />
              <span>Active Layers:</span>
            </span>

            <button
              type="button"
              onClick={() =>
                setLayerToggles((prev) => ({ ...prev, showAdjacency: !prev.showAdjacency }))
              }
              className={`px-2.5 py-1 rounded border transition-colors ${
                layerToggles.showAdjacency
                  ? 'bg-surface-muted text-text-primary border-border font-bold'
                  : 'bg-transparent text-text-muted border-transparent line-through'
              }`}
            >
              1. Zone Adjacency ({adjacency.edges.length})
            </button>

            <button
              type="button"
              onClick={() =>
                setLayerToggles((prev) => ({ ...prev, showForecastEdges: !prev.showForecastEdges }))
              }
              className={`px-2.5 py-1 rounded border transition-colors ${
                layerToggles.showForecastEdges
                  ? 'bg-surface-muted text-navy border-border font-bold'
                  : 'bg-transparent text-text-muted border-transparent line-through'
              }`}
            >
              2. Forecast Dependencies ({forecastEdges.length})
            </button>

            <button
              type="button"
              onClick={() =>
                setLayerToggles((prev) => ({ ...prev, showCascadePath: !prev.showCascadePath }))
              }
              className={`px-2.5 py-1 rounded border transition-colors ${
                layerToggles.showCascadePath
                  ? 'bg-amber-50 text-amber-900 border-amber-200 font-bold'
                  : 'bg-transparent text-text-muted border-transparent line-through'
              }`}
            >
              3. Cascade Path ({cascadeStages.length})
            </button>
          </div>

          {/* System Spec Filter */}
          <div className="flex items-center gap-2">
            <Filter size={13} className="text-text-muted" />
            <span className="text-text-muted text-[11px]">System:</span>
            <select
              aria-label="Filter systems"
              value={systemFilter}
              onChange={(e) => setSystemFilter(e.target.value)}
              className="bg-surface-muted text-xs px-2.5 py-1 rounded border border-border text-text-primary focus:outline-none font-mono"
            >
              <option value="all">All Systems ({currentConfig?.systems.length || 0})</option>
              {currentConfig?.systems.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.id.toUpperCase()} ({s.unit})
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Main 2-Column Responsive Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* Left Column: Interactive Visualizer (Graph or Spatial Map) */}
        <div className="lg:col-span-2">
          {viewMode === 'network' ? (
            <GraphCanvas
              cityConfig={currentConfig}
              forecast={latestForecast}
              isStreamConnected={isStreamConnected}
              selectedZoneId={selectedZoneId}
              selectedNodeId={selectedNodeId}
              selectedEdge={selectedEdge}
              systemFilter={systemFilter}
              onSelectZone={(zId) => setSelectedZoneId(zId)}
              onSelectNode={(nId) => setSelectedNodeId(nId)}
              onSelectEdge={(edge) => setSelectedEdge(edge)}
              expandAllSystems={expandAllSystems}
              onToggleExpandAll={() => setExpandAllSystems((prev) => !prev)}
              layerToggles={layerToggles}
            />
          ) : (
            /* Spatial GeoJSON Map View (Preserved) */
            <Card variant="cream" className="p-5 min-h-[540px] flex flex-col justify-between">
              <div className="flex items-center justify-between pb-3 border-b border-border">
                <span className="text-xs font-mono uppercase text-text-muted font-semibold">
                  GEOJSON ZONE BOUNDARIES & SPATIAL POLYGONS
                </span>
                <span className="text-[11px] font-mono text-text-primary bg-surface-muted px-2 py-0.5 rounded border border-border font-bold">
                  {geoData?.features?.length || 0} Spatial Features
                </span>
              </div>

              <div className="relative flex-1 flex items-center justify-center py-4 overflow-hidden">
                {mapProjection && geoData ? (
                  <svg
                    viewBox={`0 0 ${mapProjection.width} ${mapProjection.height}`}
                    className="w-full h-auto max-h-[460px]"
                    aria-label="Upper Assam GeoJSON Map"
                  >
                    {geoData.features.map((feat: any) => {
                      const zoneId = feat.properties?.id;
                      const zoneName = feat.properties?.name || zoneId;
                      const isSelected = selectedZoneId === zoneId;
                      const rawRisk = latestForecast?.zone_risk_states?.[zoneId];
                      const colorHex = rawRisk && rawRisk in RISK_STATE_CONFIG
                        ? RISK_STATE_CONFIG[rawRisk].colorHex
                        : '#cbd5e1';

                      const coords = feat.geometry?.coordinates;
                      let pathD = '';
                      const buildRingPath = (ring: any[]) => {
                        return (
                          ring
                            .map(([lon, lat], idx) => {
                              const [px, py] = mapProjection.project(lon, lat);
                              return `${idx === 0 ? 'M' : 'L'} ${px.toFixed(1)} ${py.toFixed(1)}`;
                            })
                            .join(' ') + ' Z'
                        );
                      };

                      if (feat.geometry?.type === 'Polygon') {
                        pathD = coords.map(buildRingPath).join(' ');
                      } else if (feat.geometry?.type === 'MultiPolygon') {
                        pathD = coords.map((p: any[]) => p.map(buildRingPath).join(' ')).join(' ');
                      }

                      const centroid = feat.properties?.centroid;
                      const [cx, cy] = centroid
                        ? mapProjection.project(centroid[0], centroid[1])
                        : [0, 0];

                      return (
                        <g
                          key={zoneId}
                          onClick={() => setSelectedZoneId(zoneId)}
                          className="cursor-pointer group"
                        >
                          <path
                            d={pathD}
                            fill={isSelected ? '#f4c52f55' : `${colorHex}30`}
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
                  <p className="text-xs text-text-muted py-12 text-center">
                    GeoJSON data not available for this city config. Switch to System & Topology Graph view.
                  </p>
                )}
              </div>
            </Card>
          )}
        </div>

        {/* Right Column: Compact City Structure Panel & Accessible Alternatives */}
        <div className="lg:col-span-1">
          <CityStructurePanel
            cityConfig={currentConfig}
            forecast={latestForecast}
            adjacency={adjacency}
            forecastEdges={forecastEdges}
            cascadeStages={cascadeStages}
            selectedZoneId={selectedZoneId}
            selectedNodeId={selectedNodeId}
            selectedEdge={selectedEdge}
            unknownNodeRecordsCount={unknownNodeRecordsCount}
            unknownNodeStagesCount={unknownNodeStagesCount}
            onSelectZone={(zId) => setSelectedZoneId(zId)}
            onSelectNode={(nId) => setSelectedNodeId(nId)}
            onSelectEdge={(edge) => setSelectedEdge(edge)}
          />
        </div>
      </div>
    </div>
  );
};
