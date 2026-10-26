import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Radio,
  Network,
  ChartNoAxesCombined,
  History,
  Database,
  Activity,
} from 'lucide-react';

export const Navigation: React.FC = () => {
  const tabs = [
    {
      to: '/',
      label: '1 Overview',
      icon: <LayoutDashboard size={15} />,
    },
    {
      to: '/operations',
      label: '2 Live Operations',
      icon: <Radio size={15} />,
    },
    {
      to: '/cascade',
      label: '3 Cascade Explorer',
      icon: <Network size={15} />,
    },
    {
      to: '/forecasts',
      label: '4 Forecasts',
      icon: <ChartNoAxesCombined size={15} />,
    },
    {
      to: '/replay',
      label: '5 Event Replay',
      icon: <History size={15} />,
    },
    {
      to: '/sources',
      label: '6 Data Sources',
      icon: <Database size={15} />,
    },
    {
      to: '/diagnostics',
      label: '7 System Diagnostics',
      icon: <Activity size={15} />,
    },
  ];

  return (
    <nav aria-label="Main Navigation" className="border-b border-border bg-[#faf7ef] sticky top-0 z-30 overflow-x-auto no-scrollbar shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-1.5 sm:py-2">
        <ul className="flex items-center space-x-1 sm:space-x-2 min-w-max">
          {tabs.map((tab) => (
            <li key={tab.to}>
              <NavLink
                to={tab.to}
                end={tab.to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-3 py-1.5 min-h-[44px] sm:min-h-0 rounded-lg text-xs font-semibold tracking-wide transition-all duration-150 ${
                    isActive
                      ? 'bg-white text-text-primary border border-text-secondary shadow-sm'
                      : 'text-text-secondary hover:text-text-primary hover:bg-surface-muted border border-transparent'
                  }`
                }
              >
                <span className="shrink-0">{tab.icon}</span>
                <span>{tab.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
};
