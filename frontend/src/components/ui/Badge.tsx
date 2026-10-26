import React from 'react';

export interface BadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'purple' | 'cyan' | 'green' | 'amber' | 'rose' | 'neutral';
  size?: 'sm' | 'md';
  icon?: React.ReactNode;
  className?: string;
  title?: string;
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'md',
  icon,
  className = '',
  title,
}) => {
  const variantStyles = {
    default: 'bg-elevated text-text-primary border-purple-primary/20',
    purple: 'bg-purple-primary/15 text-purple-300 border-purple-primary/40',
    cyan: 'bg-neon-cyan/15 text-neon-cyan border-neon-cyan/40',
    green: 'bg-neon-green/15 text-neon-green border-neon-green/40',
    amber: 'bg-warning-amber/15 text-warning-amber border-warning-amber/40',
    rose: 'bg-critical-red/15 text-critical-red border-critical-red/40',
    neutral: 'bg-zinc-800/80 text-zinc-300 border-zinc-700',
  }[variant];

  const sizeStyles = {
    sm: 'text-[10px] px-2 py-0.5 gap-1 font-medium',
    md: 'text-xs px-2.5 py-0.5 gap-1.5 font-medium',
  }[size];

  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-md border tracking-wide transition-colors ${variantStyles} ${sizeStyles} ${className}`}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      {children}
    </span>
  );
};
