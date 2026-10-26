import { useEffect, useState, useCallback } from 'react';
import { fetchHealth } from '../lib/api';

export function useBackendHealth(pollIntervalMs = 10000) {
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);
  const [service, setService] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const check = useCallback(async () => {
    try {
      const res = await fetchHealth();
      setIsHealthy(res.status === 'ok');
      setService(res.service);
      setError(null);
    } catch (err: any) {
      setIsHealthy(false);
      setError(err?.message || 'Backend unreachable');
    } finally {
      setLastChecked(new Date());
    }
  }, []);

  useEffect(() => {
    check();
    const interval = setInterval(check, pollIntervalMs);
    return () => clearInterval(interval);
  }, [check, pollIntervalMs]);

  return { isHealthy, service, lastChecked, error, checkHealth: check };
}
