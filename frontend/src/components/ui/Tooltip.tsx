import React, { useState } from 'react';

interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export const Tooltip: React.FC<TooltipProps> = ({ content, children, className = '' }) => {
  const [visible, setVisible] = useState(false);

  return (
    <div
      className={`relative inline-block ${className}`}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      {children}
      {visible && (
        <div
          role="tooltip"
          className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-1.5 text-xs font-normal text-text-primary bg-secondary/95 border border-purple-primary/30 rounded-md shadow-xl backdrop-blur-md max-w-xs whitespace-normal pointer-events-none animate-in fade-in zoom-in-95 duration-150"
        >
          {content}
          <div className="absolute top-full left-1/2 -translate-x-1/2 -mt-1 border-4 border-transparent border-t-purple-primary/40" />
        </div>
      )}
    </div>
  );
};
