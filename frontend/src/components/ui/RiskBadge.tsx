import { ShieldCheck, Eye, AlertTriangle, AlertOctagon, HelpCircle } from 'lucide-react';
import { RiskState } from '../../types/api';
import { RISK_STATE_CONFIG } from '../../lib/formatters';

interface RiskBadgeProps {
  state: RiskState | string | null | undefined;
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
  className?: string;
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({
  state,
  size = 'md',
  showIcon = true,
  className = '',
}) => {
  const isKnownState = state && state in RISK_STATE_CONFIG;
  const normalizedState = isKnownState ? (state as RiskState) : null;

  const iconSize = size === 'sm' ? 12 : size === 'lg' ? 18 : 14;

  const sizeClasses = {
    sm: 'text-[11px] px-2 py-0.5 gap-1 font-semibold tracking-wider',
    md: 'text-xs px-2.5 py-1 gap-1.5 font-semibold tracking-wider',
    lg: 'text-sm px-3.5 py-1.5 gap-2 font-bold tracking-widest',
  }[size];

  if (!normalizedState) {
    return (
      <span
        className={`inline-flex items-center rounded-md border uppercase font-mono transition-all duration-150 bg-[#ded8c9]/50 text-text-muted border-border ${sizeClasses} ${className}`}
        title="Risk State: Awaiting forecast / Unknown"
      >
        {showIcon && <HelpCircle size={iconSize} className="shrink-0 text-text-muted" />}
        <span>{state || 'NO FORECAST'}</span>
      </span>
    );
  }

  const config = RISK_STATE_CONFIG[normalizedState];

  const getIcon = () => {
    switch (normalizedState) {
      case 'NORMAL':
        return <ShieldCheck size={iconSize} className="shrink-0" />;
      case 'WATCH':
        return <Eye size={iconSize} className="shrink-0" />;
      case 'HIGH_RISK':
        return <AlertTriangle size={iconSize} className="shrink-0" />;
      case 'CRITICAL':
        return <AlertOctagon size={iconSize} className="shrink-0" />;
    }
  };

  return (
    <span
      className={`inline-flex items-center rounded-md border uppercase font-mono transition-all duration-150 ${config.bgClass} ${config.textClass} ${config.borderClass} ${sizeClasses} ${className}`}
      title={`Risk State: ${config.label}`}
    >
      {showIcon && getIcon()}
      <span>{config.label}</span>
    </span>
  );
};
