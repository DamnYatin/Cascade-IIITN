import {
  ForecastSnapshot,
  Observation,
  StreamForecastMessage,
  StreamObservationsMessage,
  WebSocketStreamMessage,
} from '../types/api';

/**
 * Validate whether an object conforms to an Observation shape.
 */
export function isValidObservation(obj: any): obj is Observation {
  return (
    obj !== null &&
    typeof obj === 'object' &&
    typeof obj.obs_id === 'string' &&
    typeof obj.source === 'string' &&
    typeof obj.source_kind === 'string' &&
    typeof obj.zone === 'string' &&
    typeof obj.system === 'string' &&
    typeof obj.value === 'number' &&
    typeof obj.event_time === 'string' &&
    typeof obj.arrival_time === 'string' &&
    Array.isArray(obj.quality_flags)
  );
}

/**
 * Validate whether an object conforms to ForecastSnapshot shape.
 */
export function isValidForecastSnapshot(obj: any): obj is ForecastSnapshot {
  return (
    obj !== null &&
    typeof obj === 'object' &&
    typeof obj.issued_at === 'string' &&
    typeof obj.city_id === 'string' &&
    typeof obj.city_risk_state === 'string' &&
    typeof obj.city_probabilities === 'object' &&
    typeof obj.zone_risk_states === 'object' &&
    typeof obj.zone_probabilities === 'object' &&
    typeof obj.evidence_quality === 'object' &&
    Array.isArray(obj.cascade_summary)
  );
}

/**
 * Validate incoming raw WebSocket message.
 */
export function validateStreamMessage(
  raw: any
): WebSocketStreamMessage | null {
  if (!raw || typeof raw !== 'object' || typeof raw.type !== 'string') {
    return null;
  }

  if (raw.type === 'observations') {
    if (typeof raw.clock_time !== 'string' || !Array.isArray(raw.observations)) {
      return null;
    }
    const validObs = raw.observations.filter(isValidObservation);
    return {
      type: 'observations',
      clock_time: raw.clock_time,
      observations: validObs,
      meta: raw.meta,
    } as StreamObservationsMessage;
  }

  if (raw.type === 'forecast') {
    if (typeof raw.clock_time !== 'string' || !isValidForecastSnapshot(raw.forecast)) {
      return null;
    }
    return {
      type: 'forecast',
      clock_time: raw.clock_time,
      forecast: raw.forecast,
    } as StreamForecastMessage;
  }

  return null;
}
