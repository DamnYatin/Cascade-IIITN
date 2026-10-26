import { CityConfigResponse, CascadeStage, RiskState, TopEdge } from '../types/api';

export type ValidRiskState = RiskState | 'unknown';

export interface ZoneAdjacencyEdge {
  id: string; // "zoneA|zoneB" (lexicographically sorted)
  source: string;
  target: string;
  isAsymmetric: boolean;
  direction?: 'bidirectional' | 'a_to_b' | 'b_to_a';
}

export interface ZoneAdjacencyResult {
  edges: ZoneAdjacencyEdge[];
  asymmetricCount: number;
  ignoredNeighbourCount: number;
}

export interface SystemNode {
  id: string; // "zone_id:system_id"
  zoneId: string;
  zoneName: string;
  systemId: string;
  displayName: string;
  unit: string;
}

export interface ForecastGraphEdge {
  id: string; // "u->v"
  source: string; // NodeId
  target: string; // NodeId
  sourceZone: string;
  targetZone: string;
  lagHours: number;
  weight: number;
  confidence: number;
}

export interface EnrichedCascadeStage extends CascadeStage {
  sourceNode?: string; // dominant_parent
  hasConnectingEdge: boolean;
  matchingEdgeId?: string;
}

export interface NodeLayoutPosition {
  id: string;
  type: 'zone' | 'system';
  zoneId: string;
  systemId?: string;
  label: string;
  subLabel?: string;
  x: number;
  y: number;
  radius: number;
  isExpanded?: boolean;
}

export interface GraphLayoutResult {
  width: number;
  height: number;
  isSchematic: boolean;
  zonePositions: Map<string, NodeLayoutPosition>;
  systemPositions: Map<string, NodeLayoutPosition>;
}

/**
 * Safe split of "zone_id:system_id".
 * Returns null if not strictly "zone_id:system_id" with exactly one colon and non-empty parts.
 */
export function parseNodeId(id: string | null | undefined): { zoneId: string; systemId: string } | null {
  if (!id || typeof id !== 'string') return null;
  const parts = id.split(':');
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  return { zoneId: parts[0], systemId: parts[1] };
}

/**
 * Returns undirected adjacency edges with stable IDs (sorted "zoneA|zoneB").
 * De-duplicates bidirectional neighbours.
 * Tracks asymmetric declarations (A lists B, B does not list A).
 * Ignores neighbour IDs not configured in city, counting them honestly.
 */
export function buildZoneAdjacency(city: CityConfigResponse | null | undefined): ZoneAdjacencyResult {
  if (!city || !city.zones || city.zones.length === 0) {
    return { edges: [], asymmetricCount: 0, ignoredNeighbourCount: 0 };
  }

  const validZoneIds = new Set(city.zones.map((z) => z.id));
  const adjacencyMap = new Map<string, { source: string; target: string; aListsB: boolean; bListsA: boolean }>();
  let ignoredNeighbourCount = 0;

  for (const zone of city.zones) {
    const fromId = zone.id;
    for (const rawToId of zone.neighbours || []) {
      if (!validZoneIds.has(rawToId)) {
        ignoredNeighbourCount++;
        continue;
      }
      if (fromId === rawToId) {
        continue; // Self-neighbour is invalid
      }

      const [minZ, maxZ] = fromId < rawToId ? [fromId, rawToId] : [rawToId, fromId];
      const edgeKey = `${minZ}|${maxZ}`;

      const existing = adjacencyMap.get(edgeKey);
      if (!existing) {
        adjacencyMap.set(edgeKey, {
          source: minZ,
          target: maxZ,
          aListsB: fromId === minZ,
          bListsA: fromId === maxZ,
        });
      } else {
        if (fromId === minZ) existing.aListsB = true;
        if (fromId === maxZ) existing.bListsA = true;
      }
    }
  }

  const edges: ZoneAdjacencyEdge[] = [];
  let asymmetricCount = 0;

  for (const [key, data] of adjacencyMap.entries()) {
    const isAsymmetric = !(data.aListsB && data.bListsA);
    if (isAsymmetric) {
      asymmetricCount++;
    }
    edges.push({
      id: key,
      source: data.source,
      target: data.target,
      isAsymmetric,
      direction: data.aListsB && data.bListsA ? 'bidirectional' : data.aListsB ? 'a_to_b' : 'b_to_a',
    });
  }

  // Stable sort by ID
  edges.sort((a, b) => a.id.localeCompare(b.id));

  return { edges, asymmetricCount, ignoredNeighbourCount };
}

/**
 * Builds system nodes with ID "zone_id:system_id".
 */
export function buildSystemNodes(city: CityConfigResponse | null | undefined): {
  systemNodes: SystemNode[];
  validNodeIds: Set<string>;
} {
  const systemNodes: SystemNode[] = [];
  const validNodeIds = new Set<string>();

  if (!city || !city.zones || !city.systems) {
    return { systemNodes, validNodeIds };
  }

  for (const zone of city.zones) {
    for (const sys of city.systems) {
      const nodeId = `${zone.id}:${sys.id}`;
      validNodeIds.add(nodeId);
      systemNodes.push({
        id: nodeId,
        zoneId: zone.id,
        zoneName: zone.name,
        systemId: sys.id,
        displayName: sys.name || sys.id,
        unit: sys.unit,
      });
    }
  }

  return { systemNodes, validNodeIds };
}

/**
 * Maps only real records from top_edges.
 * Filters out records referencing nodes not present in this city, reporting their count.
 */
export function buildForecastEdges(
  topEdges: TopEdge[] | null | undefined,
  validNodeIds: Set<string>
): {
  edges: ForecastGraphEdge[];
  unknownNodeRecordsCount: number;
} {
  if (!topEdges || topEdges.length === 0) {
    return { edges: [], unknownNodeRecordsCount: 0 };
  }

  const edges: ForecastGraphEdge[] = [];
  let unknownNodeRecordsCount = 0;

  for (const edge of topEdges) {
    const parsedU = parseNodeId(edge.u);
    const parsedV = parseNodeId(edge.v);

    if (!parsedU || !parsedV || !validNodeIds.has(edge.u) || !validNodeIds.has(edge.v)) {
      unknownNodeRecordsCount++;
      continue;
    }

    edges.push({
      id: `${edge.u}->${edge.v}`,
      source: edge.u,
      target: edge.v,
      sourceZone: parsedU.zoneId,
      targetZone: parsedV.zoneId,
      lagHours: edge.lag_hours,
      weight: edge.weight,
      confidence: edge.confidence,
    });
  }

  return { edges, unknownNodeRecordsCount };
}

/**
 * Maps cascade stages from cascade_summary.
 * Matches dominant_parent with top_edges to determine connecting edges.
 * Records referenced nodes not in this city without crashing.
 */
export function buildCascadePath(
  cascadeSummary: CascadeStage[] | null | undefined,
  forecastEdges: ForecastGraphEdge[],
  validNodeIds: Set<string>
): {
  stages: EnrichedCascadeStage[];
  unknownNodeStagesCount: number;
} {
  if (!cascadeSummary || cascadeSummary.length === 0) {
    return { stages: [], unknownNodeStagesCount: 0 };
  }

  const edgeMap = new Map<string, string>(); // "u|v" -> edgeId
  for (const e of forecastEdges) {
    edgeMap.set(`${e.source}|${e.target}`, e.id);
  }

  const stages: EnrichedCascadeStage[] = [];
  let unknownNodeStagesCount = 0;

  for (const stg of cascadeSummary) {
    const parsed = parseNodeId(stg.node);
    if (!parsed || !validNodeIds.has(stg.node)) {
      unknownNodeStagesCount++;
    }

    let hasConnectingEdge = false;
    let matchingEdgeId: string | undefined = undefined;

    if (stg.dominant_parent) {
      const matchKey = `${stg.dominant_parent}|${stg.node}`;
      if (edgeMap.has(matchKey)) {
        hasConnectingEdge = true;
        matchingEdgeId = edgeMap.get(matchKey);
      }
    }

    stages.push({
      ...stg,
      sourceNode: stg.dominant_parent || undefined,
      hasConnectingEdge,
      matchingEdgeId,
    });
  }

  // Sort by stage order ascending
  stages.sort((a, b) => a.stage - b.stage);

  return { stages, unknownNodeStagesCount };
}

/**
 * Honest risk lookup: returns valid RiskState or 'unknown'.
 * Never defaults unknown risk to 'NORMAL'.
 */
export function getRisk(rawState: string | null | undefined): ValidRiskState {
  if (rawState === 'NORMAL' || rawState === 'WATCH' || rawState === 'HIGH_RISK' || rawState === 'CRITICAL') {
    return rawState;
  }
  return 'unknown';
}

/**
 * Computes deterministic schematic positions for zones and systems.
 * Uses a fixed mathematical layout based on zone IDs and index, guaranteed stable across renders.
 */
export function computeGraphLayout(
  city: CityConfigResponse | null | undefined,
  expandedZoneId: string | null,
  expandAll: boolean
): GraphLayoutResult {
  const width = 900;
  const height = 560;
  const zonePositions = new Map<string, NodeLayoutPosition>();
  const systemPositions = new Map<string, NodeLayoutPosition>();

  if (!city || !city.zones || city.zones.length === 0) {
    return { width, height, isSchematic: true, zonePositions, systemPositions };
  }

  const zones = city.zones;
  const n = zones.length;
  const centerX = width / 2;
  const centerY = height / 2;
  const rx = Math.min(width * 0.38, 330);
  const ry = Math.min(height * 0.36, 190);

  // Distribute zones along an ellipse with fixed deterministic angles
  zones.forEach((z, index) => {
    const angle = (2 * Math.PI * index) / n - Math.PI / 2;
    // Mild deterministic perturbation based on zone ID character codes to break perfect symmetry
    const charSum = z.id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
    const radiusModX = 1 + ((charSum % 7) - 3) * 0.02;
    const radiusModY = 1 + (((charSum >> 2) % 7) - 3) * 0.02;

    const zx = centerX + rx * radiusModX * Math.cos(angle);
    const zy = centerY + ry * radiusModY * Math.sin(angle);

    const isExpanded = expandAll || z.id === expandedZoneId;

    zonePositions.set(z.id, {
      id: z.id,
      type: 'zone',
      zoneId: z.id,
      label: z.name || z.id,
      subLabel: `${city.systems?.length || 0} systems`,
      x: Math.round(zx),
      y: Math.round(zy),
      radius: isExpanded ? 52 : 36,
      isExpanded,
    });

    // Lay out systems around or inside expanded zones
    if (city.systems && city.systems.length > 0) {
      const sysCount = city.systems.length;
      const sysOrbitRadius = isExpanded ? 46 : 0;

      city.systems.forEach((sys, sIdx) => {
        const sysNodeId = `${z.id}:${sys.id}`;
        if (!isExpanded) {
          // If not expanded, position collapses to zone center for clean edge rendering
          systemPositions.set(sysNodeId, {
            id: sysNodeId,
            type: 'system',
            zoneId: z.id,
            systemId: sys.id,
            label: sys.name || sys.id,
            subLabel: sys.unit,
            x: Math.round(zx),
            y: Math.round(zy),
            radius: 8,
            isExpanded: false,
          });
        } else {
          const sAngle = (2 * Math.PI * sIdx) / sysCount;
          const sx = zx + sysOrbitRadius * Math.cos(sAngle);
          const sy = zy + sysOrbitRadius * Math.sin(sAngle);

          systemPositions.set(sysNodeId, {
            id: sysNodeId,
            type: 'system',
            zoneId: z.id,
            systemId: sys.id,
            label: sys.name || sys.id,
            subLabel: sys.unit,
            x: Math.round(sx),
            y: Math.round(sy),
            radius: 12,
            isExpanded: true,
          });
        }
      });
    }
  });

  return {
    width,
    height,
    isSchematic: true,
    zonePositions,
    systemPositions,
  };
}
