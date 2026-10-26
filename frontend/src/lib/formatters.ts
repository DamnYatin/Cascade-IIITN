import { RiskState, SourceKind } from '../types/api';

/**
 * Format an ISO timestamp string into a readable local date/time.
 */
export function formatLocalTime(isoString: string | null | undefined): string {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(d);
  } catch {
    return isoString;
  }
}

/**
 * Format an ISO timestamp into UTC string for hover/tooltip details.
 */
export function formatUtcTime(isoString: string | null | undefined): string {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toISOString().replace('.000Z', ' UTC').replace('T', ' ');
  } catch {
    return isoString;
  }
}

/**
 * Format a number with given decimal places.
 */
export function formatNumber(val: number | null | undefined, decimals = 2): string {
  if (val === null || val === undefined || isNaN(val)) return '—';
  return val.toFixed(decimals);
}

/**
 * Format a float in [0, 1] as a percentage string (e.g. 0.854 -> 85.4%).
 */
export function formatPercent(val: number | null | undefined, decimals = 1): string {
  if (val === null || val === undefined || isNaN(val)) return '—';
  return `${(val * 100).toFixed(decimals)}%`;
}

/**
 * Calculate latency in minutes between event_time and arrival_time.
 */
export function getLatencyMinutes(eventTime: string, arrivalTime: string): number {
  try {
    const e = new Date(eventTime).getTime();
    const a = new Date(arrivalTime).getTime();
    return Math.max(0, Math.round((a - e) / (1000 * 60)));
  } catch {
    return 0;
  }
}

/**
 * Format minutes into human readable duration (e.g. 1h 24m, 12m).
 */
export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

/**
 * Semantic style mapping for risk states.
 */
export const RISK_STATE_CONFIG: Record<
  RiskState,
  {
    label: string;
    bgClass: string;
    textClass: string;
    borderClass: string;
    glowClass: string;
    colorHex: string;
  }
> = {
  NORMAL: {
    label: 'NORMAL',
    bgClass: 'bg-[#42b883]/15',
    textClass: 'text-[#42b883]',
    borderClass: 'border-[#42b883]/40',
    glowClass: 'shadow-none',
    colorHex: '#42b883',
  },
  WATCH: {
    label: 'WATCH',
    bgClass: 'bg-[#64cbe3]/15',
    textClass: 'text-[#64cbe3]',
    borderClass: 'border-[#64cbe3]/40',
    glowClass: 'shadow-none',
    colorHex: '#64cbe3',
  },
  HIGH_RISK: {
    label: 'HIGH RISK',
    bgClass: 'bg-[#e8bd45]/15',
    textClass: 'text-[#e8bd45]',
    borderClass: 'border-[#e8bd45]/40',
    glowClass: 'shadow-none',
    colorHex: '#e8bd45',
  },
  CRITICAL: {
    label: 'CRITICAL',
    bgClass: 'bg-[#f17d75]/15',
    textClass: 'text-[#f17d75]',
    borderClass: 'border-[#f17d75]/40',
    glowClass: 'shadow-none',
    colorHex: '#f17d75',
  },
};

/**
 * Styling and badge description for source kind.
 */
export const SOURCE_KIND_CONFIG: Record<
  SourceKind,
  {
    label: string;
    bgClass: string;
    textClass: string;
    borderClass: string;
    description: string;
  }
> = {
  real: {
    label: 'REAL',
    bgClass: 'bg-emerald-500/15',
    textClass: 'text-emerald-400',
    borderClass: 'border-emerald-500/40',
    description: 'Direct meteorological/telemetric observations from official feeds (Open-Meteo, IMD, ERA5).',
  },
  simulated: {
    label: 'SIMULATED',
    bgClass: 'bg-purple-500/15',
    textClass: 'text-purple-300',
    borderClass: 'border-purple-500/30',
    description: 'Planted cascade synthetic model with controlled sensor noise and physics couplings.',
  },
  disaggregated: {
    label: 'DISAGGREGATED',
    bgClass: 'bg-cyan-500/15',
    textClass: 'text-cyan-300',
    borderClass: 'border-cyan-500/30',
    description: 'Spatially or temporally downscaled observations from coarse district feeds.',
  },
};
