import { CityConfigResponse, CitySummary, FaultInput, FaultResponse, ForecastSnapshot } from '../types/api';

const ENV_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/+$/, '');

/**
 * Resolve API URL:
 * When served via Vite dev server or when ENV_BASE_URL is empty, route through
 * the same-origin '/api' proxy to eliminate browser CORS restrictions with FastAPI.
 */
export function getApiUrl(path: string): string {
  const cleanPath = path.startsWith('/') ? path : `/${path}`;

  // If in browser on localhost:5173 dev server, use the same-origin Vite proxy
  if (typeof window !== 'undefined' && (window.location.port === '5173' || !ENV_BASE_URL)) {
    return `/api${cleanPath}`;
  }

  return `${ENV_BASE_URL}${cleanPath}`;
}

export function getWsUrl(path: string, queryParams: Record<string, string | number> = {}): string {
  // Normalize path to ensure it starts with /ws/ for the backend contract
  const normPath = path.startsWith('/ws/')
    ? path
    : path.startsWith('/ws')
    ? path.replace(/^\/ws/, '/ws/')
    : `/ws${path.startsWith('/') ? path : `/${path}`}`;

  let wsBase: string;
  if (typeof window !== 'undefined') {
    const loc = window.location;
    if (ENV_BASE_URL) {
      wsBase = ENV_BASE_URL.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:');
    } else {
      const protocol = loc.protocol === 'https:' ? 'wss:' : 'ws:';
      wsBase = `${protocol}//${loc.host}`;
    }
  } else {
    wsBase = 'ws://127.0.0.1:8000';
  }

  const url = new URL(`${wsBase.replace(/\/+$/, '')}${normPath}`);
  Object.entries(queryParams).forEach(([k, v]) => {
    url.searchParams.set(k, String(v));
  });

  return url.toString();
}

/**
 * Resilient fetch with automatic fallback:
 * Tries the primary URL first; if blocked by CORS or network, tries the same-origin proxy.
 */
async function resilientFetch(path: string, options?: RequestInit): Promise<Response> {
  const primaryUrl = getApiUrl(path);
  try {
    const res = await fetch(primaryUrl, options);
    return res;
  } catch (err) {
    // If primary was cross-origin and failed (e.g. CORS), fallback to same-origin /api proxy
    if (!primaryUrl.startsWith('/api')) {
      const fallbackUrl = `/api${path.startsWith('/') ? path : `/${path}`}`;
      return fetch(fallbackUrl, options);
    }
    throw err;
  }
}

export async function fetchHealth(): Promise<{ status: string; service: string }> {
  const res = await resilientFetch('/health');
  if (!res.ok) {
    throw new Error(`Health check failed: HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchCities(): Promise<CitySummary[]> {
  const res = await resilientFetch('/cities');
  if (!res.ok) {
    throw new Error(`Failed to load cities: HTTP ${res.status}`);
  }
  const data = await res.json();
  return data.cities || [];
}

export async function fetchCityConfig(cityId: string): Promise<CityConfigResponse> {
  const res = await resilientFetch(`/city/${encodeURIComponent(cityId)}`);
  if (!res.ok) {
    throw new Error(`Failed to load city config for ${cityId}: HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchLatestForecast(params: {
  city: string;
  seed?: number;
  rain_window?: string;
  anchor?: string;
}): Promise<ForecastSnapshot> {
  const sp = new URLSearchParams();
  sp.set('city', params.city);
  if (params.seed !== undefined) sp.set('seed', String(params.seed));
  if (params.rain_window) sp.set('rain_window', params.rain_window);
  if (params.anchor) sp.set('anchor', params.anchor);

  const res = await resilientFetch(`/forecast/latest?${sp.toString()}`);
  if (!res.ok) {
    throw new Error(`Failed to load forecast: HTTP ${res.status}`);
  }
  return res.json();
}

export async function submitFault(params: {
  city: string;
  seed: number;
  fault: FaultInput;
}): Promise<FaultResponse> {
  const sp = new URLSearchParams({
    city: params.city,
    seed: String(params.seed),
  });

  const res = await resilientFetch(`/faults?${sp.toString()}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params.fault),
  });

  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`Fault injection failed: HTTP ${res.status} ${errorText}`);
  }

  return res.json();
}
