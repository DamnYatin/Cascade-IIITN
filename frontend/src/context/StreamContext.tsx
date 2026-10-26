import React, { createContext, useContext, useState, useMemo } from 'react';
import { useBackendHealth } from '../hooks/useBackendHealth';
import { useCityConfig } from '../hooks/useCityConfig';
import { useReplayStream, ConnectionStatus } from '../hooks/useReplayStream';
import { CityConfigResponse, CitySummary, ForecastSnapshot, Observation } from '../types/api';

interface StreamContextType {
  selectedCityId: string;
  setSelectedCityId: (cityId: string) => void;
  cities: CitySummary[];
  currentConfig: CityConfigResponse | null;
  isLoadingConfig: boolean;
  // Health
  isBackendHealthy: boolean | null;
  healthService: string | null;
  healthError: string | null;
  checkHealth: () => void;
  // Stream
  wsStatus: ConnectionStatus;
  clockTime: string | null;
  observations: Observation[];
  totalObsCount: number;
  latestForecast: ForecastSnapshot | null;
  forecastHistory: ForecastSnapshot[];
  activeFaults: string[];
  wsError: string | null;
  reconnectAttempts: number;
  malformedMessageCount: number;
  maxObservations: number;
  streamConfig: {
    city: string;
    seed: number;
    speed: number;
    hours: number;
    rain_window: string;
    anchor: string;
    forecast: number;
  };
  updateStreamConfig: (newCfg: any) => void;
  reconnectStream: () => void;
  clearObservations: () => void;
}

const StreamContext = createContext<StreamContextType | null>(null);

export function StreamProvider({ children }: { children: React.ReactNode }) {
  const [selectedCityId, setSelectedCityId] = useState<string>('upper_assam');

  // Backend Health check hook
  const {
    isHealthy,
    service: healthService,
    error: healthError,
    checkHealth,
  } = useBackendHealth();

  // City Config loader
  const { cities, currentConfig, isLoading: isLoadingConfig } = useCityConfig(selectedCityId);

  // Streaming WebSocket Hook - mounted once at top-level
  const {
    status: wsStatus,
    clockTime,
    observations,
    totalObsCount,
    latestForecast,
    forecastHistory,
    activeFaults,
    lastError: wsError,
    reconnectAttempts,
    malformedMessageCount,
    config: streamConfig,
    updateConfig: updateStreamConfig,
    reconnect: reconnectStream,
    clearObservations,
    maxObservations,
  } = useReplayStream({
    city: selectedCityId,
    seed: 1,
    speed: 1.0,
    hours: 72,
    rain_window: 'peak',
    anchor: 'off',
    forecast: 1,
    autoConnect: true,
  });

  const value = useMemo(
    () => ({
      selectedCityId,
      setSelectedCityId: (cityId: string) => {
        setSelectedCityId(cityId);
        updateStreamConfig({ city: cityId });
      },
      cities,
      currentConfig,
      isLoadingConfig,
      isBackendHealthy: isHealthy,
      healthService,
      healthError,
      checkHealth,
      wsStatus,
      clockTime,
      observations,
      totalObsCount,
      latestForecast,
      forecastHistory,
      activeFaults,
      wsError,
      reconnectAttempts,
      malformedMessageCount,
      maxObservations,
      streamConfig,
      updateStreamConfig,
      reconnectStream,
      clearObservations,
    }),
    [
      selectedCityId,
      cities,
      currentConfig,
      isLoadingConfig,
      isHealthy,
      healthService,
      healthError,
      checkHealth,
      wsStatus,
      clockTime,
      observations,
      totalObsCount,
      latestForecast,
      forecastHistory,
      activeFaults,
      wsError,
      reconnectAttempts,
      malformedMessageCount,
      maxObservations,
      streamConfig,
      updateStreamConfig,
      reconnectStream,
      clearObservations,
    ]
  );

  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>;
}

export function useStream(): StreamContextType {
  const ctx = useContext(StreamContext);
  if (!ctx) {
    throw new Error('useStream must be used within a StreamProvider');
  }
  return ctx;
}
