import { useEffect, useRef, useState, useCallback, useReducer, useMemo } from 'react';
import { getWsUrl } from '../lib/api';
import { validateStreamMessage } from '../lib/websocket';
import {
  ForecastSnapshot,
  Observation,
  StreamForecastMessage,
  StreamObservationsMessage,
} from '../types/api';
import {
  ConnectionState,
  INITIAL_CONNECTION_STATE,
  connectionReducer,
  selectDisplayedStatus,
  DisplayedStreamStatus,
} from '../lib/connectionStateMachine';

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
  const [connState, dispatch] = useReducer(connectionReducer, INITIAL_CONNECTION_STATE);

  const [clockTime, setClockTime] = useState<string | null>(null);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [totalObsCount, setTotalObsCount] = useState<number>(0);
  const [latestForecast, setLatestForecast] = useState<ForecastSnapshot | null>(null);
  const [forecastHistory, setForecastHistory] = useState<ForecastSnapshot[]>([]);
  const [activeFaults, setActiveFaults] = useState<string[]>([]);
  const [malformedMessageCount, setMalformedMessageCount] = useState<number>(0);

  // References
  const obsBufferRef = useRef<Observation[]>([]);
  const frameIdRef = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generationRef = useRef<number>(0);
  const isConnectingRef = useRef<boolean>(false);
  const sessionObsCountRef = useRef<number>(0);
  const attemptCountRef = useRef<number>(0);
  const userIntentRef = useRef<'connected' | 'disconnected'>('connected');

  // Buffer incoming observations between animation frames for 60fps UI
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
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close(1000, 'Client unmount or config change');
      }
      wsRef.current = null;
    }
    isConnectingRef.current = false;
  }, []);

  // Connect implementation protected by generation ID and single-flight lock
  const connect = useCallback((targetConfig: ReplayStreamConfig) => {
    // Parameter validation
    if (!targetConfig.city) {
      return;
    }

    cleanupSocket();

    // Increment generation ID to invalidate any delayed events from previous sockets
    generationRef.current += 1;
    const currentGen = generationRef.current;
    isConnectingRef.current = true;
    sessionObsCountRef.current = 0;

    const connectionKey = `${targetConfig.city}:${targetConfig.seed}:${targetConfig.speed}:${targetConfig.hours}:${targetConfig.rain_window}:${targetConfig.anchor}:${targetConfig.forecast}`;

    dispatch({
      type: 'CONNECT_REQUESTED',
      connectionKey,
      generationId: currentGen,
    });

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
        if (generationRef.current !== currentGen) return;
        isConnectingRef.current = false;
        dispatch({ type: 'SOCKET_OPEN', generationId: currentGen });
      };

      socket.onmessage = (event) => {
        if (generationRef.current !== currentGen) return;
        sessionObsCountRef.current += 1;
        attemptCountRef.current = 0;
        try {
          const raw = JSON.parse(event.data);
          const validated = validateStreamMessage(raw);

          if (!validated) {
            setMalformedMessageCount((c) => c + 1);
            return;
          }

          dispatch({
            type: 'MESSAGE_RECEIVED',
            generationId: currentGen,
            timestamp: Date.now(),
          });

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
        } catch {
          setMalformedMessageCount((c) => c + 1);
        }
      };

      socket.onerror = () => {
        if (generationRef.current !== currentGen) return;
        isConnectingRef.current = false;
        dispatch({
          type: 'SOCKET_ERROR',
          generationId: currentGen,
          message: 'WebSocket transport error. Check that FastAPI backend is running on port 8000.',
        });
      };

      socket.onclose = (ev) => {
        if (generationRef.current !== currentGen) return;
        isConnectingRef.current = false;
        wsRef.current = null;

        // Clean closure: code 1000 OR if data was streamed and replay finished
        const isCompleted = ev.code === 1000 || sessionObsCountRef.current > 0;

        dispatch({
          type: 'SOCKET_CLOSE',
          generationId: currentGen,
          code: isCompleted ? 1000 : ev.code,
          reason: isCompleted ? 'Replay finished' : ev.reason,
        });

        // Reconnect with capped backoff and jitter ONLY for genuine network/transport drops before data
        if (!isCompleted && ev.code !== 1000 && userIntentRef.current === 'connected') {
          attemptCountRef.current += 1;
          if (attemptCountRef.current <= 3) {
            const attempt = attemptCountRef.current;
            const baseDelay = Math.min(1000 * Math.pow(1.5, attempt), MAX_BACKOFF_MS);
            const jitter = Math.random() * 500;
            const delay = baseDelay + jitter;

            reconnectTimeoutRef.current = setTimeout(() => {
              connect(targetConfig);
            }, delay);
          } else {
            dispatch({
              type: 'SOCKET_ERROR',
              generationId: currentGen,
              message: 'Session closed without data (replay may be completed on backend). Click Connect to restart or select a new seed.',
            });
          }
        }
      };
    } catch (err: any) {
      isConnectingRef.current = false;
      dispatch({
        type: 'SOCKET_ERROR',
        generationId: currentGen,
        message: err?.message || 'Failed to initialize WebSocket',
      });
    }
  }, [cleanupSocket, scheduleFlush]);

  // Connect on mount or when key stream parameters change
  useEffect(() => {
    if (config.autoConnect !== false) {
      userIntentRef.current = 'connected';
      attemptCountRef.current = 0;
      connect(config);
    }
    return () => {
      cleanupSocket();
      if (frameIdRef.current !== null) {
        cancelAnimationFrame(frameIdRef.current);
      }
    };
  }, [config.city, config.seed, config.speed, config.hours, config.rain_window, config.anchor, config.forecast]);

  // Stale detection interval derived from backend cadence (speed-scaled)
  useEffect(() => {
    // At speed 1.0 backend emits every ~50ms; 8s threshold gives generous margin for GC/network jitter
    const staleThresholdMs = Math.max(3000, 8000 / (config.speed || 1.0));
    const interval = setInterval(() => {
      dispatch({
        type: 'STALE_CHECK',
        now: Date.now(),
        staleThresholdMs,
      });
    }, 2000);

    return () => clearInterval(interval);
  }, [config.speed]);

  const disconnect = useCallback(() => {
    userIntentRef.current = 'disconnected';
    attemptCountRef.current = 0;
    cleanupSocket();
    dispatch({ type: 'DISCONNECT_REQUESTED' });
  }, [cleanupSocket]);

  const reconnect = useCallback(() => {
    userIntentRef.current = 'connected';
    attemptCountRef.current = 0;
    cleanupSocket();
    generationRef.current += 1;
    dispatch({ type: 'RETRY_REQUESTED', generationId: generationRef.current });
    connect(config);
  }, [config, connect, cleanupSocket]);

  const updateConfig = useCallback((newConfig: Partial<ReplayStreamConfig>) => {
    setConfig((prev) => ({ ...prev, ...newConfig }));
  }, []);

  const clearObservations = useCallback(() => {
    setObservations([]);
    setTotalObsCount(0);
  }, []);

  // Backwards-compatible legacy status mapping
  const legacyStatus: ConnectionStatus = useMemo(() => {
    if (connState.wsConnection === 'connected') return 'open';
    if (connState.wsConnection === 'connecting' || connState.wsConnection === 'reconnecting') return 'connecting';
    if (connState.wsConnection === 'error') return 'error';
    return 'closed';
  }, [connState.wsConnection]);

  // Pure selector for displayed status
  const displayedStatus: DisplayedStreamStatus = useMemo(
    () => selectDisplayedStatus(connState, true),
    [connState]
  );

  return {
    status: legacyStatus,
    connState,
    displayedStatus,
    clockTime,
    observations,
    totalObsCount,
    latestForecast,
    forecastHistory,
    activeFaults,
    lastError: connState.lastError,
    reconnectAttempts: connState.reconnectAttempts,
    malformedMessageCount,
    config,
    updateConfig,
    connect: () => connect(config),
    disconnect,
    reconnect,
    clearObservations,
    maxObservations: MAX_OBSERVATIONS,
  };
}
