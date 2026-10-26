import React, { useState } from 'react';
import {
  Layers,
  ArrowRight,
  Sliders,
  Table,
  Info,
  ExternalLink,
  Clock,
  Activity,
} from 'lucide-react';
import { Card } from '../ui/Card';
import { RiskBadge } from '../ui/RiskBadge';
import {
  CityConfigResponse,
  ForecastSnapshot,
  TopEdge,
  RiskState,
} from '../../types/api';
import {
  ZoneAdjacencyResult,
  ForecastGraphEdge,
  EnrichedCascadeStage,
  getRisk,
} from '../../lib/graphModel';
import { formatPercent } from '../../lib/formatters';

interface CityStructurePanelProps {
  cityConfig: CityConfigResponse | null;
  forecast: ForecastSnapshot | null;
  adjacency: ZoneAdjacencyResult;
  forecastEdges: ForecastGraphEdge[];
  cascadeStages: EnrichedCascadeStage[];
  selectedZoneId: string | null;
  selectedNodeId: string | null;
  selectedEdge: TopEdge | null;
  unknownNodeRecordsCount: number;
  unknownNodeStagesCount: number;
  onSelectZone: (zoneId: string) => void;
  onSelectNode: (nodeId: string | null) => void;
  onSelectEdge: (edge: TopEdge | null) => void;
}

export const CityStructurePanel: React.FC<CityStructurePanelProps> = ({
  cityConfig,
  forecast,
  adjacency,
  forecastEdges,
  cascadeStages,
  selectedZoneId,
  selectedNodeId,
  selectedEdge,
  unknownNodeRecordsCount,
  unknownNodeStagesCount,
  onSelectZone,
  onSelectNode,
  onSelectEdge,
}) => {
  const [activeTab, setActiveTab] = useState<'details' | 'edges' | 'cascade'>('details');

  const selectedZone = cityConfig?.zones.find((z) => z.id === selectedZoneId) || null;
  const selectedZoneRisk = getRisk(forecast?.zone_risk_states?.[selectedZoneId || '']);

  // If a specific system node is selected: "zoneId:systemId"
  const parsedNode = selectedNodeId ? selectedNodeId.split(':') : null;
  const selectedSysSpec = parsedNode && parsedNode[1]
    ? cityConfig?.systems.find((s) => s.id === parsedNode[1]) || null
    : null;

  const nodeStage = selectedNodeId
    ? cascadeStages.find((s) => s.node === selectedNodeId)
    : null;

  return (
    <div className="space-y-4">
      {/* Tab Switcher for Details vs Accessible Tables */}
      <div className="flex bg-surface-muted p-1 rounded-lg border border-border">
        <button
          type="button"
          onClick={() => setActiveTab('details')}
          className={`flex-1 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'details'
              ? 'bg-white text-text-primary border border-border shadow-sm'
              : 'text-text-secondary hover:text-text-primary'
          }`}
        >
          <Info size={13} />
          <span>Structure & Detail</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('edges')}
          className={`flex-1 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'edges'
              ? 'bg-white text-text-primary border border-border shadow-sm'
              : 'text-text-secondary hover:text-text-primary'
          }`}
        >
          <Table size={13} />
          <span>Edges ({forecastEdges.length})</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('cascade')}
          className={`flex-1 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'cascade'
              ? 'bg-white text-text-primary border border-border shadow-sm'
              : 'text-text-secondary hover:text-text-primary'
          }`}
        >
          <Activity size={13} />
          <span>Cascade ({cascadeStages.length})</span>
        </button>
      </div>

      {/* TAB 1: STRUCTURE & SELECTED DETAILS */}
      {activeTab === 'details' && (
        <div className="space-y-4">
          {/* City Summary Metrics Card */}
          <Card variant="cream">
            <div className="flex items-center justify-between pb-2.5 border-b border-border">
              <div>
                <span className="text-[10px] font-mono uppercase text-text-muted font-bold tracking-wider">
                  CITY STRUCTURE
                </span>
                <h3 className="font-heading text-base font-bold text-text-primary">
                  {cityConfig?.city_id ? cityConfig.city_id.toUpperCase().replace('_', ' ') : '—'}
                </h3>
              </div>
              <span className="text-xs font-mono font-bold bg-navy text-white px-2 py-0.5 rounded">
                Threshold {cityConfig?.critical_stress_threshold ?? 0.8}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 mt-3 text-xs font-mono">
              <div className="p-2 rounded bg-white border border-border">
                <span className="text-text-muted block text-[10px]">ZONES</span>
                <span className="text-sm font-bold text-text-primary">{cityConfig?.zones.length || 0}</span>
              </div>
              <div className="p-2 rounded bg-white border border-border">
                <span className="text-text-muted block text-[10px]">CONFIGURED SYSTEMS</span>
                <span className="text-sm font-bold text-text-primary">{cityConfig?.systems.length || 0}</span>
              </div>
              <div className="p-2 rounded bg-white border border-border">
                <span className="text-text-muted block text-[10px]">ZONE ADJACENCY EDGES</span>
                <span className="text-sm font-bold text-text-primary">{adjacency.edges.length}</span>
                {adjacency.asymmetricCount > 0 && (
                  <span className="text-[10px] text-amber-700 block mt-0.5">
                    ({adjacency.asymmetricCount} asymmetric)
                  </span>
                )}
              </div>
              <div className="p-2 rounded bg-white border border-border">
                <span className="text-text-muted block text-[10px]">FORECAST DEPENDENCY EDGES</span>
                <span className="text-sm font-bold text-navy">{forecastEdges.length}</span>
              </div>
            </div>

            {/* Note about API domain prior edges */}
            <div className="mt-3 p-2 rounded bg-surface-muted border border-border/80 text-[11px] text-text-secondary leading-snug">
              <span className="font-bold text-text-primary block mb-0.5">Prior Structure Notice:</span>
              The backend city endpoint does not expose configured domain prior edges to the frontend. Only the forecaster's live forecast-reported dependencies (<code className="font-mono text-navy font-bold">top_edges</code>) are visualized.
            </div>

            {/* Ignored or Unknown Nodes Report if non-zero */}
            {(adjacency.ignoredNeighbourCount > 0 || unknownNodeRecordsCount > 0 || unknownNodeStagesCount > 0) && (
              <div className="mt-2 p-2 rounded bg-amber-50 border border-amber-200 text-[11px] text-amber-900 font-mono">
                {adjacency.ignoredNeighbourCount > 0 && (
                  <p>• {adjacency.ignoredNeighbourCount} neighbour declarations referenced unknown zones.</p>
                )}
                {unknownNodeRecordsCount > 0 && (
                  <p>• {unknownNodeRecordsCount} forecast edge records referenced nodes not in this city.</p>
                )}
                {unknownNodeStagesCount > 0 && (
                  <p>• {unknownNodeStagesCount} cascade stages referenced nodes not in this city.</p>
                )}
              </div>
            )}
          </Card>

          {/* Selected Node Details (if system node selected) */}
          {selectedNodeId && (
            <Card variant="navy">
              <div className="flex items-center justify-between pb-2 border-b border-[#1e2c4f]">
                <div>
                  <span className="text-[10px] font-mono uppercase text-accent-gold font-bold">
                    SELECTED SYSTEM NODE
                  </span>
                  <h4 className="font-mono text-sm font-bold text-white break-words">
                    {selectedNodeId}
                  </h4>
                </div>
                <button
                  type="button"
                  onClick={() => onSelectNode(null)}
                  className="text-xs text-text-navy-muted hover:text-white"
                >
                  Clear
                </button>
              </div>

              <div className="mt-3 space-y-2 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-text-navy-muted">System Spec:</span>
                  <span className="text-white font-bold">{selectedSysSpec?.id || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-navy-muted">Metric Unit:</span>
                  <span className="text-white font-bold">{selectedSysSpec?.unit || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-navy-muted">Parent Zone:</span>
                  <button
                    type="button"
                    onClick={() => parsedNode && onSelectZone(parsedNode[0])}
                    className="text-accent-gold underline hover:text-white font-bold"
                  >
                    {parsedNode ? parsedNode[0] : '—'}
                  </button>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-text-navy-muted">Cascade Status:</span>
                  {nodeStage ? (
                    <span className="text-accent-gold font-bold">
                      Stage #{nodeStage.stage} (P={formatPercent(nodeStage.probability)})
                    </span>
                  ) : (
                    <span className="text-emerald-400 font-semibold">Stable (No Cascade Stage)</span>
                  )}
                </div>
              </div>
            </Card>
          )}

          {/* Selected Edge Details (if forecast edge selected) */}
          {selectedEdge && (
            <Card variant="navy">
              <div className="flex items-center justify-between pb-2 border-b border-[#1e2c4f]">
                <div>
                  <span className="text-[10px] font-mono uppercase text-accent-gold font-bold">
                    SELECTED DEPENDENCY EDGE
                  </span>
                  <div className="flex items-center gap-1.5 font-mono text-xs font-bold text-white mt-0.5">
                    <span>{selectedEdge.u}</span>
                    <ArrowRight size={12} className="text-accent-gold" />
                    <span>{selectedEdge.v}</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onSelectEdge(null)}
                  className="text-xs text-text-navy-muted hover:text-white"
                >
                  Clear
                </button>
              </div>

              <div className="mt-3 space-y-2 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-text-navy-muted">Coupling Weight:</span>
                  <span className="text-white font-bold">{selectedEdge.weight.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-navy-muted">Confidence:</span>
                  <span className="text-white font-bold">{formatPercent(selectedEdge.confidence)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-navy-muted">Lag Duration:</span>
                  <span className="text-white font-bold">+{selectedEdge.lag_hours} hours</span>
                </div>
                <div className="pt-2 border-t border-[#1e2c4f] text-[11px] text-text-navy-muted leading-tight">
                  {selectedEdge.weight >= 0
                    ? 'Positive coupling: stress in source node increases predicted stress on target.'
                    : 'Negative coupling: stress in source node relieves stress on target.'}
                </div>
              </div>
            </Card>
          )}

          {/* Selected Zone Overview */}
          <Card variant="cream">
            <div className="flex items-center justify-between pb-2.5 border-b border-border">
              <div>
                <span className="text-[10px] font-mono uppercase text-text-muted font-bold">
                  SELECTED ZONE DETAILS
                </span>
                <h4 className="font-heading text-base font-bold text-text-primary">
                  {selectedZone?.name || selectedZoneId || 'None'}
                </h4>
                <p className="text-[11px] font-mono text-text-muted">ID: {selectedZoneId || '—'}</p>
              </div>
              {selectedZoneId && (
                <RiskBadge
                  state={selectedZoneRisk === 'unknown' ? null : (selectedZoneRisk as RiskState)}
                  size="md"
                />
              )}
            </div>

            <div className="mt-3 space-y-2.5 text-xs">
              <div className="flex justify-between">
                <span className="text-text-secondary">Direct Neighbours ({selectedZone?.neighbours?.length || 0}):</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {selectedZone?.neighbours && selectedZone.neighbours.length > 0 ? (
                  selectedZone.neighbours.map((nbr) => (
                    <button
                      key={nbr}
                      type="button"
                      onClick={() => onSelectZone(nbr)}
                      className="text-[11px] font-mono px-2 py-0.5 rounded bg-white border border-border hover:border-navy text-text-secondary hover:text-text-primary transition-colors font-semibold"
                    >
                      {nbr}
                    </button>
                  ))
                ) : (
                  <span className="text-text-muted text-[11px]">None declared</span>
                )}
              </div>

              {/* Verified fields absent from API are labeled honestly */}
              <div className="pt-2 border-t border-border/60 space-y-1.5 text-[11px] text-text-muted">
                <div className="flex justify-between">
                  <span>Coordinates (Lat/Lon):</span>
                  <span className="font-mono text-text-secondary">
                    {selectedZone?.centroid_lat !== undefined && selectedZone?.centroid_lon !== undefined
                      ? `${selectedZone.centroid_lat}, ${selectedZone.centroid_lon}`
                      : 'Not provided by API'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Jurisdiction / Role:</span>
                  <span className="font-mono text-text-secondary">
                    {selectedZone?.jurisdiction || selectedZone?.role || 'Not provided by API'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>River Links / Assets:</span>
                  <span className="font-mono text-text-secondary">Not provided by API</span>
                </div>
              </div>
            </div>
          </Card>

          {/* Recent Edge Changes (from EdgeBook) */}
          {forecast?.edge_changes && forecast.edge_changes.length > 0 && (
            <Card variant="cream">
              <div className="flex items-center gap-1.5 pb-2 border-b border-border text-xs font-mono font-bold text-text-primary">
                <Clock size={13} className="text-navy" />
                <span>RECENT DEPENDENCY CHANGES ({forecast.edge_changes.length})</span>
              </div>
              <div className="mt-2 space-y-2 text-xs font-mono">
                {forecast.edge_changes.slice(0, 5).map((ch, idx) => (
                  <div key={idx} className="p-2 rounded bg-white border border-border text-[11px]">
                    <div className="flex items-center justify-between font-bold text-navy">
                      <span>{ch.u} → {ch.v}</span>
                      <span className="uppercase text-[10px] text-amber-700">{ch.kind}</span>
                    </div>
                    <div className="text-text-muted mt-0.5">
                      w: {ch.old_weight.toFixed(3)} → {ch.new_weight.toFixed(3)}
                    </div>
                    {ch.reason && <div className="text-text-secondary text-[10px] mt-0.5 italic">{ch.reason}</div>}
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* TAB 2: ACCESSIBLE FORECAST EDGES TABLE */}
      {activeTab === 'edges' && (
        <Card variant="cream" className="p-4">
          <div className="flex items-center justify-between pb-2 border-b border-border mb-3">
            <h4 className="font-heading text-sm font-bold text-text-primary">
              Forecast Dependency Edges
            </h4>
            <span className="text-xs font-mono text-text-muted">{forecastEdges.length} Total</span>
          </div>

          {forecastEdges.length > 0 ? (
            <div className="overflow-x-auto max-h-[460px] overflow-y-auto">
              <table className="w-full text-left text-xs font-mono border-collapse" aria-label="Forecast dependencies table">
                <thead>
                  <tr className="border-b border-border text-text-muted text-[10px] uppercase">
                    <th className="py-1.5 px-2">Source</th>
                    <th className="py-1.5 px-2">Target</th>
                    <th className="py-1.5 px-2 text-right">Lag</th>
                    <th className="py-1.5 px-2 text-right">Weight</th>
                    <th className="py-1.5 px-2 text-right">Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {forecastEdges.map((e) => {
                    const isSelected = selectedEdge?.u === e.source && selectedEdge?.v === e.target;
                    return (
                      <tr
                        key={e.id}
                        onClick={() =>
                          onSelectEdge({
                            u: e.source,
                            v: e.target,
                            lag_hours: e.lagHours,
                            weight: e.weight,
                            confidence: e.confidence,
                          })
                        }
                        className={`border-b border-border/50 cursor-pointer transition-colors ${
                          isSelected ? 'bg-amber-100 font-bold' : 'hover:bg-white'
                        }`}
                      >
                        <td className="py-1.5 px-2 text-navy">{e.source}</td>
                        <td className="py-1.5 px-2 text-text-primary">{e.target}</td>
                        <td className="py-1.5 px-2 text-right">+{e.lagHours}h</td>
                        <td className={`py-1.5 px-2 text-right ${e.weight >= 0 ? 'text-navy' : 'text-sky-700'}`}>
                          {e.weight.toFixed(3)}
                        </td>
                        <td className="py-1.5 px-2 text-right">{formatPercent(e.confidence)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-text-muted py-6 text-center">
              No forecast-reported dependencies in latest forecast.
            </p>
          )}
        </Card>
      )}

      {/* TAB 3: ACCESSIBLE CASCADE STAGES TABLE */}
      {activeTab === 'cascade' && (
        <Card variant="navy" className="p-4">
          <div className="flex items-center justify-between pb-2 border-b border-[#1e2c4f] mb-3">
            <h4 className="font-heading text-sm font-bold text-white">
              Predicted Cascade Stages
            </h4>
            <span className="text-xs font-mono text-accent-gold">{cascadeStages.length} Stages</span>
          </div>

          {cascadeStages.length > 0 ? (
            <div className="overflow-x-auto max-h-[460px] overflow-y-auto space-y-2">
              {cascadeStages.map((stg) => (
                <div
                  key={`${stg.stage}-${stg.node}`}
                  onClick={() => onSelectNode(stg.node)}
                  className="p-2.5 rounded bg-navy-card border border-[#1e2c4f] text-xs font-mono cursor-pointer hover:border-accent-gold transition-colors"
                >
                  <div className="flex items-center justify-between text-white font-bold">
                    <span className="flex items-center gap-1.5">
                      <span className="h-5 w-5 rounded-full bg-amber-600 text-white flex items-center justify-center text-[10px]">
                        #{stg.stage}
                      </span>
                      <span>{stg.node}</span>
                    </span>
                    <span className="text-accent-gold">P = {formatPercent(stg.probability)}</span>
                  </div>
                  <div className="mt-1 text-[11px] text-text-navy-muted flex justify-between">
                    <span>Parent: {stg.dominant_parent || 'Direct precipitation shock'}</span>
                    <span>
                      ETA:{' '}
                      {stg.eta_p10 !== null && stg.eta_p90 !== null
                        ? `+${stg.eta_p10?.toFixed(1)}h – +${stg.eta_p90?.toFixed(1)}h`
                        : '—'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-text-navy-muted py-6 text-center">
              No cascade stages predicted in latest forecast.
            </p>
          )}
        </Card>
      )}
    </div>
  );
};
