import React from 'react';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  variant?: 'cream' | 'navy';
  severityStripe?: 'normal' | 'watch' | 'high' | 'critical' | null;
  className?: string;
}

export const Card: React.FC<CardProps> = ({
  children,
  variant = 'cream',
  severityStripe,
  className = '',
  ...props
}) => {
  const stripeColor = {
    normal: 'border-l-4 border-l-risk-normal',
    watch: 'border-l-4 border-l-risk-watch',
    high: 'border-l-4 border-l-risk-high',
    critical: 'border-l-4 border-l-risk-critical',
  };

  const stripeClass = severityStripe ? stripeColor[severityStripe] : '';

  const variantClass =
    variant === 'navy'
      ? 'bg-navy-deep border border-[#1e2c4f] text-white shadow-card-navy'
      : 'bg-surface border border-border text-text-primary shadow-card-subtle';

  return (
    <div
      className={`rounded-xl p-5 relative overflow-hidden transition-all duration-200 ${variantClass} ${stripeClass} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};
