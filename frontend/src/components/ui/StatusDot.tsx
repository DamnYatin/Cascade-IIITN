import React from 'react';

export type StatusVariant = 'online' | 'connecting' | 'offline' | 'warning' | 'critical';

interface StatusDotProps {
  status: StatusVariant;
  label?: string;
  pulse?: boolean;
  className?: string;
}

export const StatusDot: React.FC<StatusDotProps> = ({
  status,
  label,
  pulse = true,
  className = '',
}) => {
  const colorMap: Record<StatusVariant, { dot: string; glow: string }> = {
    online: { dot: 'bg-accent-gold', glow: 'bg-accent-gold/40' },
    connecting: { dot: 'bg-risk-watch', glow: 'bg-risk-watch/40' },
    warning: { dot: 'bg-risk-high', glow: 'bg-risk-high/40' },
    critical: { dot: 'bg-risk-critical', glow: 'bg-risk-critical/40' },
    offline: { dot: 'bg-zinc-400', glow: 'bg-zinc-400/20' },
  };

  const { dot, glow } = colorMap[status] || colorMap.offline;

  return (
    <div className={`inline-flex items-center gap-2 ${className}`}>
      <span className="relative flex h-2.5 w-2.5 items-center justify-center">
        {pulse && status !== 'offline' && (
          <span
            className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${glow}`}
          />
        )}
        <span className={`relative inline-flex rounded-full h-2 w-2 ${dot}`} />
      </span>
      {label && <span className="text-xs font-mono font-bold uppercase tracking-wider">{label}</span>}
    </div>
  );
};
