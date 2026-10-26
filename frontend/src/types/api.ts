export type RiskState = 'NORMAL' | 'WATCH' | 'HIGH_RISK' | 'CRITICAL';

export type SourceKind = 'real' | 'simulated' | 'disaggregated';

export interface Zone {
  id: string;
  name: string;
  neighbours: string[];
  centroid_lat?: number;
  centroid_lon?: number;
  systems?: string[];
  jurisdiction?: string;
  role?: string;
  river_links?: Array<{ name: string; role: string }>;
  assets?: Record<string, any> | Array<Record<string, any>>;
}

export interface SystemSpec {
  id: string;
  name?: string;
  unit: string;
  capacity?: number;
  critical_threshold?: number;
}

export interface StreamSpec {
  source: string;
  system: string;
  cadence_hours: number;
  typical_delay_hours: number;
  noise_level: number;
  source_kind: SourceKind;
  false_report_rate?: number;
}

export interface Edge {
  u: string;
  v: string;
  lag_hours: number;
  weight: number;
  confidence: number;
  last_updated?: string;
}

export interface CitySummary {
  city_id: string;
  zones: number;
  systems: string[];
  streams: string[];
  start_time_utc: string;
}

export interface CityConfigResponse {
  city_id: string;
  zones: Zone[];
  systems: SystemSpec[];
  start_time_utc: string;
  critical_stress_threshold: number;
}

export interface Observation {
  obs_id: string;
  source: string;
  source_kind: SourceKind;
  zone: string;
  system: string;
  value: number;
  event_time: string;
  arrival_time: string;
  quality_flags: string[];
  node_id?: string;
}

export interface CascadeStage {
  stage: number;
  node: string;
  probability: number;
  eta_p10?: number | null;
  eta_p50?: number | null;
  eta_p90?: number | null;
  dominant_parent?: string | null;
}

export interface TopEdge {
  u: string;
  v: string;
  lag_hours: number;
  weight: number;
  confidence: number;
}

export interface EdgeChange {
  time: string;
  u: string;
  v: string;
  kind: string;
  old_weight: number;
  new_weight: number;
  reason: string;
}

export interface DriftEvent {
  node: string;
  time: string;
  detector: string;
  magnitude: number;
}

export interface ForecastSnapshot {
  issued_at: string;
  city_id: string;
  city_risk_state: RiskState;
  city_probabilities: Record<string, Record<string, number>>;
  zone_risk_states: Record<string, RiskState>;
  zone_probabilities: Record<string, Record<string, Record<string, number>>>;
  evidence_quality: Record<string, number>;
  top_edges: TopEdge[];
  edge_changes: EdgeChange[];
  drift_events: DriftEvent[];
  cascade_summary: CascadeStage[];
  provenance_mix: Record<string, any>;
  disclosure_string: string;
  burn_in: boolean;
  calibrated: boolean;
  oracle: boolean;
  config_hash: string;
}

export interface StreamObservationsMessage {
  type: 'observations';
  clock_time: string;
  observations: Observation[];
  meta?: {
    city?: string;
    seed?: number;
    released_count?: number;
    faults?: string[];
    anchor_mode?: string;
  };
}

export interface StreamForecastMessage {
  type: 'forecast';
  clock_time: string;
  forecast: ForecastSnapshot;
}

export type WebSocketStreamMessage = StreamObservationsMessage | StreamForecastMessage;

export interface FaultInput {
  kind: 'dropout' | 'stuck_at' | 'spike' | 'feed_delay' | 'contradictory_duplicate' | 'citizen_spam' | 'blackout' | string;
  target_zone?: string;
  target_system?: string;
  start_hour?: number;
  end_hour?: number;
  probability?: number;
  delay_hours?: number;
  stuck_value?: number;
  spike_magnitude?: number;
  burst_count?: number;
}

export interface FaultResponse {
  ok: boolean;
  session: string;
  fault: string;
  faults_applied: string[];
  fault_log_entries: number;
}
