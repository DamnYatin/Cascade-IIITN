import React, { useRef, useState, useMemo, useEffect, useCallback } from 'react';
import {
  ZoomIn,
  ZoomOut,
  Maximize2,
  HelpCircle,
  AlertTriangle,
  AlertOctagon,
  CheckCircle,
  Eye,
  Layers,
  Info,
} from 'lucide-react';
import {
  CityConfigResponse,
  ForecastSnapshot,
  TopEdge,
  RiskState,
} from '../../types/api';
import {
  buildZoneAdjacency,
  buildSystemNodes,
  buildForecastEdges,
  buildCascadePath,
  computeGraphLayout,
  getRisk,
  ValidRiskState,
  ZoneAdjacencyEdge,
  ForecastGraphEdge,
  EnrichedCascadeStage,
  NodeLayoutPosition,
} from '../../lib/graphModel';
import { formatPercent } from '../../lib/formatters';

interface GraphCanvasProps {
  cityConfig: CityConfigResponse | null;
  forecast: ForecastSnapshot | null;
  isStreamConnected: boolean;
  selectedZoneId: string | null;
  selectedNodeId: string | null;
  selectedEdge: TopEdge | null;
  systemFilter: string;
  onSelectZone: (zoneId: string | null) => void;
  onSelectNode: (nodeId: string | null) => void;
  onSelectEdge: (edge: TopEdge | null) => void;
  expandAllSystems: boolean;
  onToggleExpandAll: () => void;
  layerToggles: {
    showAdjacency: boolean;
    showForecastEdges: boolean;
    showCascadePath: boolean;
    showEdgeChanges: boolean;
  };
}

const RISK_ICONS: Record<ValidRiskState, React.ReactNode> = {
  NORMAL: <CheckCircle size={10} className="text-emerald-500" />,
  WATCH: <Eye size={10} className="text-sky-500" />,
  HIGH_RISK: <AlertTriangle size={10} className="text-amber-500" />,
  CRITICAL: <AlertOctagon size={10} className="text-red-500" />,
  unknown: <HelpCircle size={10} className="text-slate-400" />,
};

const RISK_COLORS: Record<ValidRiskState, { fill: string; stroke: string; text: string }> = {
  NORMAL: { fill: '#ecfdf5', stroke: '#10b981', text: '#065f46' },
  WATCH: { fill: '#f0f9ff', stroke: '#0ea5e9', text: '#0369a1' },
  HIGH_RISK: { fill: '#fffbeb', stroke: '#f59e0b', text: '#92400e' },
  CRITICAL: { fill: '#fef2f2', stroke: '#ef4444', text: '#991b1b' },
  unknown: { fill: '#f8fafc', stroke: '#94a3b8', text: '#475569' },
};

export const GraphCanvas: React.FC<GraphCanvasProps> = ({
  cityConfig,
  forecast,
  isStreamConnected,
  selectedZoneId,
  selectedNodeId,
  selectedEdge,
  systemFilter,
  onSelectZone,
  onSelectNode,
  onSelectEdge,
  expandAllSystems,
  onToggleExpandAll,
  layerToggles,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  // Transform state for pan and zoom
  const [transform, setTransform] = useState<{ x: number; y: number; k: number }>({
    x: 0,
    y: 0,
    k: 1.0,
  });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Hover state for tooltip
  const [hoveredItem, setHoveredItem] = useState<{
    type: 'zone' | 'system' | 'adjacency' | 'forecast_edge';
    id: string;
    label: string;
    subLabel?: string;
    details?: string;
    x: number;
    y: number;
  } | null>(null);

  // 1. Compute pure graph models
  const adjacency = useMemo(() => buildZoneAdjacency(cityConfig), [cityConfig]);
  const { validNodeIds } = useMemo(() => buildSystemNodes(cityConfig), [cityConfig]);

  const { edges: forecastEdges } = useMemo(
    () => buildForecastEdges(forecast?.top_edges, validNodeIds),
    [forecast?.top_edges, validNodeIds]
  );

  const { stages: cascadeStages } = useMemo(
    () => buildCascadePath(forecast?.cascade_summary, forecastEdges, validNodeIds),
    [forecast?.cascade_summary, forecastEdges, validNodeIds]
  );

  // 2. Compute deterministic layout once per city and expansion state
  const layout = useMemo(
    () => computeGraphLayout(cityConfig, selectedZoneId, expandAllSystems),
    [cityConfig, selectedZoneId, expandAllSystems]
  );

  // Filtered system nodes if systemFilter != 'all'
  const visibleSystemPositions = useMemo(() => {
    const map = new Map<string, NodeLayoutPosition>();
    for (const [id, pos] of layout.systemPositions.entries()) {
      if (systemFilter === 'all' || pos.systemId === systemFilter) {
        map.set(id, pos);
      }
    }
    return map;
  }, [layout.systemPositions, systemFilter]);

  // Connected elements to selected item for focus/de-emphasis
  const activeFocusSet = useMemo(() => {
    const connectedNodes = new Set<string>();
    const connectedEdges = new Set<string>();

    if (selectedNodeId) {
      connectedNodes.add(selectedNodeId);
      const parts = selectedNodeId.split(':');
      if (parts[0]) connectedNodes.add(parts[0]); // add parent zone

      // check forecast edges connected to this node
      forecastEdges.forEach((e) => {
        if (e.source === selectedNodeId || e.target === selectedNodeId) {
          connectedEdges.add(e.id);
          connectedNodes.add(e.source);
          connectedNodes.add(e.target);
        }
      });
    } else if (selectedZoneId) {
      connectedNodes.add(selectedZoneId);

      // check adjacent zones
      adjacency.edges.forEach((e) => {
        if (e.source === selectedZoneId || e.target === selectedZoneId) {
          connectedEdges.add(e.id);
          connectedNodes.add(e.source);
          connectedNodes.add(e.target);
        }
      });

      // check forecast edges touching this zone
      forecastEdges.forEach((e) => {
        if (e.sourceZone === selectedZoneId || e.targetZone === selectedZoneId) {
          connectedEdges.add(e.id);
          connectedNodes.add(e.source);
          connectedNodes.add(e.target);
        }
      });
    } else if (selectedEdge) {
      connectedEdges.add(`${selectedEdge.u}->${selectedEdge.v}`);
      connectedNodes.add(selectedEdge.u);
      connectedNodes.add(selectedEdge.v);
    }

    return { connectedNodes, connectedEdges, hasSelection: Boolean(selectedNodeId || selectedZoneId || selectedEdge) };
  }, [selectedNodeId, selectedZoneId, selectedEdge, forecastEdges, adjacency.edges]);

  // Reset / Fit to view
  const handleResetZoom = useCallback(() => {
    setTransform({ x: 0, y: 0, k: 1.0 });
  }, []);

  const handleZoom = (deltaK: number) => {
    setTransform((prev) => {
      const nextK = Math.min(Math.max(0.4, prev.k + deltaK), 2.5);
      return { ...prev, k: nextK };
    });
  };

  // Mouse wheel zoom
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 0.1 : -0.1;
    handleZoom(factor);
  };

  // Drag pan
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return; // primary click only
    setIsDragging(true);
    dragStartRef.current = { x: e.clientX - transform.x, y: e.clientY - transform.y };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setTransform((prev) => ({
      ...prev,
      x: e.clientX - dragStartRef.current.x,
      y: e.clientY - dragStartRef.current.y,
    }));
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  // Keyboard navigation for canvas
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === '+' || e.key === '=') {
      handleZoom(0.15);
    } else if (e.key === '-' || e.key === '_') {
      handleZoom(-0.15);
    } else if (e.key === '0') {
      handleResetZoom();
    } else if (e.key === 'Escape') {
      onSelectZone(null);
      onSelectNode(null);
      onSelectEdge(null);
    }
  };

  return (
    <div
      ref={containerRef}
      role="region"
      aria-label="City Topology and Dependency Graph Canvas"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      className="relative w-full h-[540px] bg-[#faf8f3] rounded-lg border border-border select-none overflow-hidden cursor-grab active:cursor-grabbing focus:outline-none focus:ring-2 focus:ring-navy/30"
    >
      {/* Top Controls Overlay */}
      <div className="absolute top-3 left-3 z-10 flex flex-wrap items-center gap-2 pointer-events-auto">
        {/* Schematic Layout Badge */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-white/90 backdrop-blur-sm border border-border text-[11px] font-mono text-text-secondary shadow-sm">
          <Info size={12} className="text-text-muted" />
          <span>Schematic layout (positions are not geographic)</span>
        </div>

        {/* Expand All Systems Toggle */}
        <button
          type="button"
          onClick={onToggleExpandAll}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-mono border transition-all shadow-sm ${
            expandAllSystems
              ? 'bg-navy text-white border-navy font-bold'
              : 'bg-white/90 text-text-secondary border-border hover:text-text-primary'
          }`}
          title="Toggle displaying all system nodes across every zone"
        >
          <Layers size={12} />
          <span>{expandAllSystems ? 'Collapse System Nodes' : 'Expand All Systems'}</span>
        </button>
      </div>

      {/* Top Right Zoom Controls */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1 bg-white/90 backdrop-blur-sm p-1 rounded-lg border border-border shadow-sm pointer-events-auto">
        <button
          type="button"
          onClick={() => handleZoom(0.15)}
          className="p-1.5 rounded hover:bg-surface-muted text-text-secondary hover:text-text-primary transition-colors"
          title="Zoom In (+)"
          aria-label="Zoom In"
        >
          <ZoomIn size={14} />
        </button>
        <button
          type="button"
          onClick={() => handleZoom(-0.15)}
          className="p-1.5 rounded hover:bg-surface-muted text-text-secondary hover:text-text-primary transition-colors"
          title="Zoom Out (-)"
          aria-label="Zoom Out"
        >
          <ZoomOut size={14} />
        </button>
        <div className="h-4 w-px bg-border my-auto mx-0.5" />
        <button
          type="button"
          onClick={handleResetZoom}
          className="p-1.5 rounded hover:bg-surface-muted text-text-secondary hover:text-text-primary transition-colors text-[11px] font-mono font-bold"
          title="Fit to View / Reset (0)"
          aria-label="Reset View"
        >
          <Maximize2 size={13} />
        </button>
      </div>

      {/* Honest Stream / Forecast Status Banner */}
      <div className="absolute bottom-3 left-3 z-10 pointer-events-auto">
        {!isStreamConnected ? (
          <div className="px-3 py-1.5 rounded bg-red-50 text-red-700 border border-red-200 text-xs font-mono shadow-sm">
            Stream disconnected — awaiting backend connection
          </div>
        ) : !forecast ? (
          <div className="px-3 py-1.5 rounded bg-amber-50 text-amber-800 border border-amber-200 text-xs font-mono shadow-sm flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
            <span>Connected, awaiting forecast...</span>
          </div>
        ) : forecast.top_edges.length === 0 ? (
          <div className="px-3 py-1.5 rounded bg-white/95 text-text-secondary border border-border text-xs font-mono shadow-sm">
            No forecast-reported dependencies in latest forecast (showing zone topology)
          </div>
        ) : null}
      </div>

      {/* Interactive SVG Surface */}
      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="w-full h-full"
        onClick={() => {
          onSelectZone(null);
          onSelectNode(null);
          onSelectEdge(null);
        }}
      >
        <defs>
          {/* Arrowheads for forecast dependency edges */}
          <marker
            id="arrow-positive"
            viewBox="0 0 10 10"
            refX="20"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#10224a" />
          </marker>
          <marker
            id="arrow-negative"
            viewBox="0 0 10 10"
            refX="20"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#0284c7" />
          </marker>
          <marker
            id="arrow-cascade"
            viewBox="0 0 10 10"
            refX="20"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#d97706" />
          </marker>
        </defs>

        <g
          transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}
          style={{ transformOrigin: 'center center' }}
        >
          {/* LAYER 1: Zone Adjacency Edges (Subtle neutral stroke, no arrowhead) */}
          {layerToggles.showAdjacency && (
            <g aria-label="Zone Adjacency Edges">
              {adjacency.edges.map((edge) => {
                const posA = layout.zonePositions.get(edge.source);
                const posB = layout.zonePositions.get(edge.target);
                if (!posA || !posB) return null;

                const isEdgeFocused = activeFocusSet.connectedEdges.has(edge.id);
                const isDeemphasized = activeFocusSet.hasSelection && !isEdgeFocused;

                return (
                  <line
                    key={edge.id}
                    x1={posA.x}
                    y1={posA.y}
                    x2={posB.x}
                    y2={posB.y}
                    stroke="#cbd5e1"
                    strokeWidth={isEdgeFocused ? 2.5 : 1.5}
                    strokeDasharray={edge.isAsymmetric ? '4 3' : undefined}
                    opacity={isDeemphasized ? 0.25 : 0.85}
                    className="transition-all duration-150"
                  />
                );
              })}
            </g>
          )}

          {/* LAYER 2: Forecast Dependency Edges (Directional, weight-scaled stroke) */}
          {layerToggles.showForecastEdges && (
            <g aria-label="Forecast-Reported Dependency Edges">
              {forecastEdges.map((edge) => {
                const posU = layout.systemPositions.get(edge.source);
                const posV = layout.systemPositions.get(edge.target);
                if (!posU || !posV) return null;

                // Scale stroke width: weight is in [-1, 1], scale between 1.5px and 4px
                const strokeWidth = Math.min(Math.max(1.5, Math.abs(edge.weight) * 3.5), 5);
                const isPositive = edge.weight >= 0;
                const markerId = isPositive ? 'url(#arrow-positive)' : 'url(#arrow-negative)';
                const strokeColor = isPositive ? '#10224a' : '#0284c7';

                const isEdgeSelected =
                  selectedEdge && selectedEdge.u === edge.source && selectedEdge.v === edge.target;
                const isEdgeFocused = isEdgeSelected || activeFocusSet.connectedEdges.has(edge.id);
                const isDeemphasized = activeFocusSet.hasSelection && !isEdgeFocused;

                return (
                  <g
                    key={edge.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectEdge({
                        u: edge.source,
                        v: edge.target,
                        lag_hours: edge.lagHours,
                        weight: edge.weight,
                        confidence: edge.confidence,
                      });
                      onSelectNode(null);
                    }}
                    onMouseEnter={() =>
                      setHoveredItem({
                        type: 'forecast_edge',
                        id: edge.id,
                        label: `${edge.source} → ${edge.target}`,
                        subLabel: `Lag: +${edge.lagHours}h | Weight: ${edge.weight.toFixed(3)} | Conf: ${formatPercent(edge.confidence)}`,
                        details: isPositive
                          ? 'Positive coupling: source stress increases target stress'
                          : 'Negative coupling: source stress relieves target stress',
                        x: (posU.x + posV.x) / 2,
                        y: (posU.y + posV.y) / 2,
                      })
                    }
                    onMouseLeave={() => setHoveredItem(null)}
                    className="cursor-pointer group"
                  >
                    {/* Wider hit zone for touch & click */}
                    <line
                      x1={posU.x}
                      y1={posU.y}
                      x2={posV.x}
                      y2={posV.y}
                      stroke="transparent"
                      strokeWidth={14}
                    />
                    <line
                      x1={posU.x}
                      y1={posU.y}
                      x2={posV.x}
                      y2={posV.y}
                      stroke={isEdgeSelected ? '#f59e0b' : strokeColor}
                      strokeWidth={isEdgeSelected ? strokeWidth + 1.5 : strokeWidth}
                      markerEnd={markerId}
                      opacity={isDeemphasized ? 0.2 : isEdgeSelected ? 1 : 0.85}
                      className="transition-all duration-150"
                    />
                  </g>
                );
              })}
            </g>
          )}

          {/* LAYER 3: Predicted Cascade Path Highlights & Stage Badges */}
          {layerToggles.showCascadePath && (
            <g aria-label="Predicted Cascade Path">
              {cascadeStages.map((stage) => {
                const targetPos = layout.systemPositions.get(stage.node);
                if (!targetPos) return null;

                const parentPos = stage.dominant_parent
                  ? layout.systemPositions.get(stage.dominant_parent)
                  : null;

                return (
                  <g key={`stage-${stage.stage}-${stage.node}`}>
                    {/* Connecting line to dominant parent if parent exists */}
                    {parentPos && (
                      <line
                        x1={parentPos.x}
                        y1={parentPos.y}
                        x2={targetPos.x}
                        y2={targetPos.y}
                        stroke="#d97706"
                        strokeWidth={2.5}
                        strokeDasharray="6 3"
                        markerEnd="url(#arrow-cascade)"
                        className="animate-pulse"
                      />
                    )}

                    {/* Stage number badge */}
                    <circle
                      cx={targetPos.x + 14}
                      cy={targetPos.y - 14}
                      r={9}
                      fill="#d97706"
                      stroke="#ffffff"
                      strokeWidth={1.5}
                      className="shadow-md"
                    />
                    <text
                      x={targetPos.x + 14}
                      y={targetPos.y - 11}
                      textAnchor="middle"
                      className="text-[9px] font-mono font-bold fill-white pointer-events-none"
                    >
                      {stage.stage}
                    </text>
                  </g>
                );
              })}
            </g>
          )}

          {/* ZONE NODES */}
          {Array.from(layout.zonePositions.values()).map((zonePos) => {
            const isSelected = selectedZoneId === zonePos.zoneId;
            const isFocused = isSelected || activeFocusSet.connectedNodes.has(zonePos.zoneId);
            const isDeemphasized = activeFocusSet.hasSelection && !isFocused;

            const rawRisk = forecast?.zone_risk_states?.[zonePos.zoneId];
            const riskState = getRisk(rawRisk);
            const riskStyle = RISK_COLORS[riskState];

            return (
              <g
                key={zonePos.id}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectZone(zonePos.zoneId);
                  onSelectNode(null);
                  onSelectEdge(null);
                }}
                onMouseEnter={() =>
                  setHoveredItem({
                    type: 'zone',
                    id: zonePos.zoneId,
                    label: zonePos.label,
                    subLabel: `Zone ID: ${zonePos.zoneId} | Risk: ${riskState}`,
                    x: zonePos.x,
                    y: zonePos.y,
                  })
                }
                onMouseLeave={() => setHoveredItem(null)}
                className="cursor-pointer group"
                tabIndex={0}
                role="button"
                aria-label={`Zone ${zonePos.label}, risk ${riskState}`}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelectZone(zonePos.zoneId);
                  }
                }}
              >
                {/* Zone Cluster Boundary Circle */}
                <circle
                  cx={zonePos.x}
                  cy={zonePos.y}
                  r={zonePos.radius}
                  fill={isSelected ? '#fef3c7' : zonePos.isExpanded ? '#ffffff' : riskStyle.fill}
                  stroke={isSelected ? '#10224a' : riskStyle.stroke}
                  strokeWidth={isSelected ? 3 : 1.5}
                  opacity={isDeemphasized ? 0.25 : 1}
                  className="transition-all duration-200"
                />

                {/* Zone Name Label */}
                <text
                  x={zonePos.x}
                  y={zonePos.isExpanded ? zonePos.y - zonePos.radius - 8 : zonePos.y - 2}
                  textAnchor="middle"
                  className="text-[11px] font-mono font-bold fill-text-primary pointer-events-none drop-shadow-sm"
                  opacity={isDeemphasized ? 0.3 : 1}
                >
                  {zonePos.label}
                </text>

                {/* Sub-label (risk state & system count) */}
                {!zonePos.isExpanded && (
                  <text
                    x={zonePos.x}
                    y={zonePos.y + 12}
                    textAnchor="middle"
                    className="text-[9px] font-mono fill-text-muted pointer-events-none"
                    opacity={isDeemphasized ? 0.3 : 1}
                  >
                    {riskState} • {zonePos.subLabel}
                  </text>
                )}
              </g>
            );
          })}

          {/* SYSTEM NODES (Rendered when expanded) */}
          {Array.from(visibleSystemPositions.values()).map((sysPos) => {
            if (!sysPos.isExpanded) return null; // collapsed inside zone

            const isSelected = selectedNodeId === sysPos.id;
            const isFocused = isSelected || activeFocusSet.connectedNodes.has(sysPos.id);
            const isDeemphasized = activeFocusSet.hasSelection && !isFocused;

            // Check if node is part of cascade stage
            const stage = cascadeStages.find((s) => s.node === sysPos.id);
            const zoneRisk = getRisk(forecast?.zone_risk_states?.[sysPos.zoneId]);
            const nodeColor = stage ? '#f59e0b' : RISK_COLORS[zoneRisk].stroke;

            return (
              <g
                key={sysPos.id}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectNode(sysPos.id);
                  onSelectZone(sysPos.zoneId);
                  onSelectEdge(null);
                }}
                onMouseEnter={() =>
                  setHoveredItem({
                    type: 'system',
                    id: sysPos.id,
                    label: sysPos.label,
                    subLabel: `Node: ${sysPos.id} | Unit: ${sysPos.subLabel}`,
                    details: stage ? `Cascade Stage #${stage.stage} (P=${formatPercent(stage.probability)})` : undefined,
                    x: sysPos.x,
                    y: sysPos.y,
                  })
                }
                onMouseLeave={() => setHoveredItem(null)}
                className="cursor-pointer group"
                tabIndex={0}
                role="button"
                aria-label={`System ${sysPos.label} in ${sysPos.zoneId}`}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelectNode(sysPos.id);
                  }
                }}
              >
                <circle
                  cx={sysPos.x}
                  cy={sysPos.y}
                  r={sysPos.radius}
                  fill={isSelected ? '#10224a' : '#ffffff'}
                  stroke={isSelected ? '#d97706' : nodeColor}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  opacity={isDeemphasized ? 0.25 : 1}
                  className="transition-all duration-150"
                />

                {/* Short identifier inside circle */}
                <text
                  x={sysPos.x}
                  y={sysPos.y + 3}
                  textAnchor="middle"
                  className={`text-[8px] font-mono font-bold pointer-events-none ${
                    isSelected ? 'fill-white' : 'fill-text-primary'
                  }`}
                  opacity={isDeemphasized ? 0.3 : 1}
                >
                  {sysPos.systemId?.slice(0, 3).toUpperCase()}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Floating Tooltip */}
      {hoveredItem && (
        <div
          className="absolute z-20 pointer-events-none bg-navy text-white text-xs p-2.5 rounded shadow-lg border border-border/20 max-w-xs font-mono transition-opacity duration-150"
          style={{
            left: Math.min(Math.max(16, hoveredItem.x * transform.k + transform.x), (containerRef.current?.clientWidth || 600) - 220),
            top: Math.max(16, hoveredItem.y * transform.k + transform.y - 70),
          }}
        >
          <div className="font-bold text-accent-gold">{hoveredItem.label}</div>
          {hoveredItem.subLabel && <div className="text-[11px] text-text-navy-muted">{hoveredItem.subLabel}</div>}
          {hoveredItem.details && <div className="text-[10px] text-risk-watch mt-1">{hoveredItem.details}</div>}
        </div>
      )}

      {/* Legend Overlay */}
      <div className="absolute bottom-3 right-3 z-10 bg-white/95 backdrop-blur-sm p-2.5 rounded-lg border border-border shadow-sm text-[11px] font-mono space-y-2 pointer-events-auto max-w-[280px]">
        <div className="font-bold text-text-primary border-b border-border pb-1 flex items-center justify-between">
          <span>GRAPH LEGEND</span>
          <span className="text-[10px] font-normal text-text-muted">4 Layers</span>
        </div>

        {/* Data Layers Legend */}
        <div className="space-y-1 text-text-secondary">
          <div className="flex items-center gap-2">
            <span className="w-5 h-0.5 bg-slate-400 inline-block" />
            <span>Zone Adjacency (Undirected)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-5 h-0.5 bg-navy inline-block" />
            <span>Forecast Dependency (+ stress)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-5 h-0.5 bg-sky-600 inline-block" />
            <span>Forecast Dependency (- stress)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-5 h-0.5 border-t-2 border-dashed border-amber-600 inline-block" />
            <span>Cascade Path (#stage)</span>
          </div>
        </div>

        {/* Risk Encodings Legend */}
        <div className="border-t border-border pt-1.5 flex flex-wrap gap-x-2 gap-y-1 text-[10px]">
          {(['NORMAL', 'WATCH', 'HIGH_RISK', 'CRITICAL', 'unknown'] as ValidRiskState[]).map((r) => (
            <div key={r} className="flex items-center gap-1">
              {RISK_ICONS[r]}
              <span className="capitalize">{r === 'unknown' ? 'Unknown' : r.toLowerCase()}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
