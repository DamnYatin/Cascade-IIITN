import React from 'react';
import { Loader2 } from 'lucide-react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'gold' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  icon?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  icon,
  className = '',
  disabled,
  ...props
}) => {
  const baseStyles =
    'inline-flex items-center justify-center font-medium rounded-lg transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-navy focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed select-none active:scale-[0.99]';

  const sizeStyles = {
    sm: 'text-xs px-3 py-1.5 gap-1.5 min-h-[34px]',
    md: 'text-sm px-4 py-2 gap-2 min-h-[40px]',
    lg: 'text-base px-5 py-2.5 gap-2.5 min-h-[46px]',
  }[size];

  const variantStyles = {
    primary:
      'bg-navy text-white hover:bg-navy-deep border border-navy shadow-sm',
    secondary:
      'bg-surface-muted text-text-primary hover:bg-[#e4ddcc] border border-border',
    outline:
      'bg-transparent text-navy hover:bg-surface-muted border border-border',
    gold:
      'bg-navy-deep text-accent-gold hover:bg-[#152345] border border-accent-gold font-mono tracking-wider shadow-sm',
    danger:
      'bg-risk-critical/10 text-risk-critical hover:bg-risk-critical/20 border border-risk-critical/40',
    ghost:
      'bg-transparent text-text-secondary hover:text-text-primary hover:bg-surface-muted',
  }[variant];

  return (
    <button
      className={`${baseStyles} ${sizeStyles} ${variantStyles} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <Loader2 size={size === 'sm' ? 14 : size === 'lg' ? 20 : 16} className="animate-spin shrink-0" />
      ) : (
        icon && <span className="shrink-0">{icon}</span>
      )}
      <span>{children}</span>
    </button>
  );
};
