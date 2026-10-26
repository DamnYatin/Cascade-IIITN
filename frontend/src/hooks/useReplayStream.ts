import { useEffect, useRef, useState, useCallback } from 'react';
import { getWsUrl } from '../lib/api';
import { validateStreamMessage } from '../lib/websocket';
import { ForecastSnapshot, Observation, StreamForecastMessage, StreamObservationsMessage } from '../types/api';

export interface ReplayStreamConfig {
  city: string;
  seed: number;
  speed: number;
  hours: number;
  rain_window: string;
  anchor: string;
  forecast: number;
  autoConnect?: boolean;
}

export type ConnectionStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

const MAX_OBSERVATIONS = 300;
const MAX_BACKOFF_MS = 10000;

export function useReplayStream(initialConfig: ReplayStreamConfig) {
  const [config, setConfig] = useState<ReplayStreamConfig>(initialConfig);
  const [status, setStatus] = useState<ConnectionStatus>('idle');
  const [clockTime, setClockTime] = useState<string | null>(null);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [totalObsCount, setTotalObsCount] = useState<number>(0);
  const [latestForecast, setLatestForecast] = useState<ForecastSnapshot | null>(null);
  const [forecastHistory, setForecastHistory] = useState<ForecastSnapshot[]>([]);
  const [activeFaults, setActiveFaults] = useState<string[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [reconnectAttempts, setReconnectAttempts] = useState<number>(0);
  const [malformedMessageCount, setMalformedMessageCount] = useState<number>(0);

  // Buffer incoming observations between animation frames for 60fps UI
  const obsBufferRef = useRef<Observation[]>([]);
  const frameIdRef = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const manualDisconnectRef = useRef<boolean>(false);
  const attemptCountRef = useRef<number>(0);

  const flushBuffer = useCallback(() => {
    if (obsBufferRef.current.length > 0) {
      const incoming = obsBufferRef.current;
      obsBufferRef.current = [];
      setObservations((prev) => {
        const combined = [...incoming.reverse(), ...prev];
        return combined.slice(0, MAX_OBSERVATIONS);
      });
      setTotalObsCount((c) => c + incoming.length);
    }
    frameIdRef.current = null;
  }, []);

  const scheduleFlush = useCallback(() => {
    if (frameIdRef.current === null) {
      frameIdRef.current = requestAnimationFrame(flushBuffer);
    }
  }, [flushBuffer]);

  const cleanupSocket = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      // Remove handlers before closing to prevent spurious onclose loops
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close(1000, 'Client unmount or config change');
      }
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback((targetConfig: ReplayStreamConfig) => {
    cleanupSocket();
    manualDisconnectRef.current = false;
    setStatus('connecting');
    setLastError(null);

    const wsUrl = getWsUrl('/stream', {
      city: targetConfig.city,
      seed: targetConfig.seed,
      speed: targetConfig.speed,
      hours: targetConfig.hours,
      rain_window: targetConfig.rain_window,
      anchor: targetConfig.anchor,
      forecast: targetConfig.forecast,
    });

    try {
      const socket = new WebSocket(wsUrl);
      wsRef.current = socket;

      socket.onopen = () => {
        setStatus('open');
        setLastError(null);
        attemptCountRef.current = 0;
        setReconnectAttempts(0);
      };

      socket.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data);
          const validated = validateStreamMessage(raw);

          if (!validated) {
            setMalformedMessageCount((c) => c + 1);
            return;
          }

          if (validated.type === 'observations') {
            const obsMsg = validated as StreamObservationsMessage;
            setClockTime(obsMsg.clock_time);
            if (obsMsg.meta?.faults) {
              setActiveFaults(obsMsg.meta.faults);
            }
            if (obsMsg.observations.length > 0) {
              obsBufferRef.current.push(...obsMsg.observations);
              scheduleFlush();
            }
          } else if (validated.type === 'forecast') {
            const fMsg = validated as StreamForecastMessage;
            setClockTime(fMsg.clock_time);
            setLatestForecast(fMsg.forecast);
            setForecastHistory((prev) => [fMsg.forecast, ...prev.slice(0, 19)]);
          }
        } catch (err: any) {
          setMalformedMessageCount((c) => c + 1);
        }
      };

      socket.onerror = () => {
        setStatus('error');
        setLastError('WebSocket transport error. Check that FastAPI backend is running on port 8000.');
      };

      socket.onclose = (ev) => {
        setStatus('closed');
        wsRef.current = null;

        if (!manualDisconnectRef.current) {
          // Exponential backoff with jitter
          const attempt = attemptCountRef.current + 1;
          attemptCountRef.current = attempt;
          setReconnectAttempts(attempt);
          const baseDelay = Math.min(1000 * Math.pow(1.5, attempt), MAX_BACKOFF_MS);
          const jitter = Math.random() * 500;
          const delay = baseDelay + jitter;

          reconnectTimeoutRef.current = setTimeout(() => {
            connect(targetConfig);
          }, delay);
        }
      };
    } catch (err: any) {
      setStatus('error');
      setLastError(err?.message || 'Failed to initialize WebSocket');
    }
  }, [cleanupSocket, scheduleFlush]);

  // Connect on mount or when key stream parameters change
  useEffect(() => {
    if (config.autoConnect !== false) {
      connect(config);
    }
    return () => {
      manualDisconnectRef.current = true;
      cleanupSocket();
      if (frameIdRef.current !== null) {
        cancelAnimationFrame(frameIdRef.current);
      }
    };
  }, [config.city, config.seed, config.speed, config.hours, config.rain_window, config.anchor, config.forecast]);

  const disconnect = useCallback(() => {
    manualDisconnectRef.current = true;
    cleanupSocket();
    setStatus('closed');
  }, [cleanupSocket]);

  const reconnect = useCallback(() => {
    manualDisconnectRef.current = false;
    attemptCountRef.current = 0;
    setReconnectAttempts(0);
    connect(config);
  }, [config, connect]);

  const updateConfig = useCallback((newConfig: Partial<ReplayStreamConfig>) => {
    setConfig((prev) => ({ ...prev, ...newConfig }));
  }, []);

  const clearObservations = useCallback(() => {
    setObservations([]);
    setTotalObsCount(0);
  }, []);

  return {
    status,
    clockTime,
    observations,
    totalObsCount,
    latestForecast,
    forecastHistory,
    activeFaults,
    lastError,
    reconnectAttempts,
    malformedMessageCount,
    config,
    updateConfig,
    disconnect,
    reconnect,
    clearObservations,
    maxObservations: MAX_OBSERVATIONS,
  };
}
