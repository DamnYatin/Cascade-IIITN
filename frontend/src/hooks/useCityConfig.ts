import { useEffect, useState, useCallback } from 'react';
import { fetchCities, fetchCityConfig } from '../lib/api';
import { CityConfigResponse, CitySummary } from '../types/api';

export function useCityConfig(selectedCityId: string) {
  const [cities, setCities] = useState<CitySummary[]>([]);
  const [currentConfig, setCurrentConfig] = useState<CityConfigResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Load cities list
  const loadCities = useCallback(async () => {
    try {
      const list = await fetchCities();
      setCities(list);
    } catch (err: any) {
      setError(err?.message || 'Failed to fetch cities');
    }
  }, []);

  // Load active city config
  const loadConfig = useCallback(async (cityId: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const cfg = await fetchCityConfig(cityId);
      setCurrentConfig(cfg);
    } catch (err: any) {
      setError(err?.message || `Failed to fetch config for ${cityId}`);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCities();
  }, [loadCities]);

  useEffect(() => {
    if (selectedCityId) {
      loadConfig(selectedCityId);
    }
  }, [selectedCityId, loadConfig]);

  return {
    cities,
    currentConfig,
    isLoading,
    error,
    refreshCities: loadCities,
    reloadConfig: () => loadConfig(selectedCityId),
  };
}
