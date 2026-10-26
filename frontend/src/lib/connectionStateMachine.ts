/**
 * Pure connection state machine and selectors for The 72-Hour Warning.
 *
 * Models three independent concepts:
 * 1. Backend Health: 'checking' | 'online' | 'offline' | 'error'
 * 2. WebSocket Connection: 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error'
 * 3. Stream Activity: 'awaiting_data' | 'active' | 'stale' | 'completed' | 'stopped' | 'error'
 *
 * Enforces:
 * - User intent tracking ('connected' vs 'disconnected')
 * - Generation ID validation to prevent stale event overwrites
 * - Normal finite replay completion (code 1000) does NOT trigger reconnect loops
 * - Single pure selector for consistent status rendering across all 7 views
 */

export type BackendHealth = 'checking' | 'online' | 'offline' | 'error';
export type WebSocketConnection = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error';
export type StreamActivity = 'awaiting_data' | 'active' | 'stale' | 'completed' | 'stopped' | 'error';
export type UserIntent = 'connected' | 'disconnected';

export interface ConnectionState {
  userIntent: UserIntent;
  wsConnection: WebSocketConnection;
  streamActivity: StreamActivity;
  generationId: number;
  connectionKey: string;
  lastMessageReceiptTime: number | null;
  reconnectAttempts: number;
  lastError: string | null;
  normalClosureReceived: boolean;
}

export type ConnectionAction =
  | { type: 'CONNECT_REQUESTED'; connectionKey: string; generationId: number }
  | { type: 'DISCONNECT_REQUESTED' }
  | { type: 'RETRY_REQUESTED'; generationId: number }
  | { type: 'SOCKET_OPEN'; generationId: number }
  | { type: 'MESSAGE_RECEIVED'; generationId: number; timestamp: number }
  | { type: 'SOCKET_CLOSE'; generationId: number; code: number; reason: string }
  | { type: 'SOCKET_ERROR'; generationId: number; message: string }
  | { type: 'STALE_CHECK'; now: number; staleThresholdMs: number }
  | { type: 'RESET_ATTEMPTS' };

export const INITIAL_CONNECTION_STATE: ConnectionState = {
  userIntent: 'connected',
  wsConnection: 'disconnected',
  streamActivity: 'stopped',
  generationId: 0,
  connectionKey: '',
  lastMessageReceiptTime: null,
  reconnectAttempts: 0,
  lastError: null,
  normalClosureReceived: false,
};

export function connectionReducer(state: ConnectionState, action: ConnectionAction): ConnectionState {
  switch (action.type) {
    case 'CONNECT_REQUESTED':
      return {
        ...state,
        userIntent: 'connected',
        wsConnection: 'connecting',
        streamActivity: 'awaiting_data',
        generationId: action.generationId,
        connectionKey: action.connectionKey,
        lastError: null,
        normalClosureReceived: false,
      };

    case 'DISCONNECT_REQUESTED':
      return {
        ...state,
        userIntent: 'disconnected',
        wsConnection: 'disconnected',
        streamActivity: 'stopped',
        reconnectAttempts: 0,
        lastError: null,
      };

    case 'RETRY_REQUESTED':
      return {
        ...state,
        userIntent: 'connected',
        wsConnection: 'connecting',
        streamActivity: 'awaiting_data',
        generationId: action.generationId,
        lastError: null,
        reconnectAttempts: 0,
        normalClosureReceived: false,
      };

    case 'SOCKET_OPEN':
      if (action.generationId !== state.generationId) return state;
      return {
        ...state,
        wsConnection: 'connected',
        streamActivity: state.lastMessageReceiptTime ? 'active' : 'awaiting_data',
        reconnectAttempts: 0,
        lastError: null,
      };

    case 'MESSAGE_RECEIVED':
      if (action.generationId !== state.generationId) return state;
      return {
        ...state,
        wsConnection: 'connected',
        streamActivity: 'active',
        lastMessageReceiptTime: action.timestamp,
      };

    case 'SOCKET_CLOSE': {
      if (action.generationId !== state.generationId) return state;

      // Normal closure: code 1000 indicates intentional end or completed replay stream
      const isNormalCompletion = action.code === 1000;

      if (isNormalCompletion) {
        return {
          ...state,
          wsConnection: 'disconnected',
          streamActivity: 'completed',
          normalClosureReceived: true,
          reconnectAttempts: 0,
        };
      }

      // Abnormal closure while user intent is connected -> enter reconnecting state
      if (state.userIntent === 'connected') {
        const nextAttempts = state.reconnectAttempts + 1;
        if (nextAttempts > 3) {
          return {
            ...state,
            wsConnection: 'error',
            streamActivity: 'completed',
            reconnectAttempts: nextAttempts,
            lastError: 'Replay session finished on backend or transport closed. Click Restart or select a new seed.',
          };
        }
        return {
          ...state,
          wsConnection: 'reconnecting',
          streamActivity: 'error',
          reconnectAttempts: nextAttempts,
          lastError: action.reason || `Connection lost (code ${action.code})`,
        };
      }

      // Disconnected per user intent
      return {
        ...state,
        wsConnection: 'disconnected',
        streamActivity: 'stopped',
      };
    }

    case 'SOCKET_ERROR':
      if (action.generationId !== state.generationId) return state;
      return {
        ...state,
        wsConnection: 'error',
        streamActivity: 'error',
        lastError: action.message,
      };

    case 'STALE_CHECK': {
      // Stale hysteresis: apply only if active and threshold exceeded, without disconnecting
      if (
        state.wsConnection === 'connected' &&
        state.streamActivity === 'active' &&
        state.lastMessageReceiptTime !== null &&
        action.now - state.lastMessageReceiptTime > action.staleThresholdMs
      ) {
        return {
          ...state,
          streamActivity: 'stale',
        };
      }
      return state;
    }

    case 'RESET_ATTEMPTS':
      return {
        ...state,
        reconnectAttempts: 0,
      };

    default:
      return state;
  }
}

/**
 * Pure selector for displayed stream status and Connect button behavior.
 * All pages and components consume this selector to ensure unanimous agreement.
 */
export interface DisplayedStreamStatus {
  variant: 'online' | 'connecting' | 'offline' | 'critical' | 'completed' | 'stale';
  label: string;
  badgeClass: string;
  pulse: boolean;
  buttonState: 'connect' | 'connecting' | 'disconnect' | 'retry';
  buttonLabel: string;
  isConnecting: boolean;
  statusAriaLabel: string;
}

export function selectDisplayedStatus(
  connState: ConnectionState,
  isBackendHealthy: boolean | null
): DisplayedStreamStatus {
  // If backend health probe explicitly reports offline
  if (isBackendHealthy === false) {
    return {
      variant: 'critical',
      label: 'BACKEND OFFLINE',
      badgeClass: 'bg-risk-critical/15 text-risk-critical border-risk-critical/30',
      pulse: false,
      buttonState: 'retry',
      buttonLabel: 'Retry',
      isConnecting: false,
      statusAriaLabel: 'Backend service offline',
    };
  }

  // Connecting state
  if (connState.wsConnection === 'connecting') {
    return {
      variant: 'connecting',
      label: 'CONNECTING...',
      badgeClass: 'bg-navy/15 text-navy border-navy/30',
      pulse: true,
      buttonState: 'connecting',
      buttonLabel: 'Connecting…',
      isConnecting: true,
      statusAriaLabel: 'Establishing WebSocket connection',
    };
  }

  // Reconnecting state
  if (connState.wsConnection === 'reconnecting') {
    return {
      variant: 'connecting',
      label: `RECONNECTING (${connState.reconnectAttempts})`,
      badgeClass: 'bg-risk-watch/15 text-risk-watch border-risk-watch/40',
      pulse: true,
      buttonState: 'connecting',
      buttonLabel: 'Reconnecting…',
      isConnecting: true,
      statusAriaLabel: `Reconnecting attempt ${connState.reconnectAttempts}`,
    };
  }

  // Error state
  if (connState.wsConnection === 'error') {
    return {
      variant: 'critical',
      label: 'STREAM ERROR',
      badgeClass: 'bg-risk-critical/15 text-risk-critical border-risk-critical/30',
      pulse: false,
      buttonState: 'retry',
      buttonLabel: 'Retry',
      isConnecting: false,
      statusAriaLabel: 'WebSocket transport error',
    };
  }

  // Connected state: distinguish stream activity
  if (connState.wsConnection === 'connected') {
    if (connState.streamActivity === 'active') {
      return {
        variant: 'online',
        label: 'STREAM ACTIVE',
        badgeClass: 'bg-[#34351e] border-[#565735] text-accent-gold',
        pulse: true,
        buttonState: 'disconnect',
        buttonLabel: 'Disconnect',
        isConnecting: false,
        statusAriaLabel: 'Live stream active receiving telemetry',
      };
    }

    if (connState.streamActivity === 'awaiting_data') {
      return {
        variant: 'online',
        label: 'CONNECTED · AWAITING DATA',
        badgeClass: 'bg-[#1e2a38] border-[#2d4158] text-sky-300',
        pulse: true,
        buttonState: 'disconnect',
        buttonLabel: 'Disconnect',
        isConnecting: false,
        statusAriaLabel: 'Connected awaiting telemetry packets',
      };
    }

    if (connState.streamActivity === 'stale') {
      return {
        variant: 'stale',
        label: 'STREAM STALE (PAUSED)',
        badgeClass: 'bg-amber-900/30 text-amber-300 border-amber-700/50',
        pulse: false,
        buttonState: 'disconnect',
        buttonLabel: 'Disconnect',
        isConnecting: false,
        statusAriaLabel: 'Connected stream is stale no recent packets',
      };
    }
  }

  // Completed finite replay
  if (connState.streamActivity === 'completed' || connState.normalClosureReceived) {
    return {
      variant: 'completed',
      label: 'REPLAY COMPLETED',
      badgeClass: 'bg-[#1e3427] border-[#2e573d] text-emerald-300',
      pulse: false,
      buttonState: 'connect',
      buttonLabel: 'Restart',
      isConnecting: false,
      statusAriaLabel: 'Replay session completed normally',
    };
  }

  // Idle / Standby
  return {
    variant: 'offline',
    label: 'STANDBY (DISCONNECTED)',
    badgeClass: 'bg-surface-muted text-text-muted border-border',
    pulse: false,
    buttonState: 'connect',
    buttonLabel: 'Connect',
    isConnecting: false,
    statusAriaLabel: 'Stream disconnected standby',
  };
}
