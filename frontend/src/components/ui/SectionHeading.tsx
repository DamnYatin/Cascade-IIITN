import React from 'react';

interface SectionHeadingProps {
  title: string;
  subtitle?: string;
  badge?: React.ReactNode;
  action?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
  as?: 'h1' | 'h2';
}

export const SectionHeading: React.FC<SectionHeadingProps> = ({
  title,
  subtitle,
  badge,
  action,
  icon,
  className = '',
  as = 'h1',
}) => {
  const HeadingTag = as;

  return (
    <div className={`flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5 ${className}`}>
      <div className="flex items-center gap-3 min-w-0">
        {icon && (
          <div className="p-2 rounded-lg bg-surface-muted border border-border text-text-primary shrink-0 shadow-sm">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <HeadingTag className="font-heading text-lg sm:text-xl font-bold tracking-tight text-text-primary px-1 py-0.5 -mx-1 -my-0.5 rounded outline-offset-2 focus:outline-2 focus:outline-navy focus-visible:outline-2 focus-visible:outline-navy transition-all break-words">
              {title}
            </HeadingTag>
            {badge && <div className="shrink-0">{badge}</div>}
          </div>
          {subtitle && (
            <p className="text-xs text-text-muted mt-1.5 leading-relaxed">{subtitle}</p>
          )}
        </div>
      </div>
      {action && <div className="flex items-center gap-2 self-start sm:self-center shrink-0">{action}</div>}
    </div>
  );
};
