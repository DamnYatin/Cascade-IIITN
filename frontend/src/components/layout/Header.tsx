import React from 'react';
import { ShieldAlert, Globe, ChevronDown } from 'lucide-react';
import { StatusDot, StatusVariant } from '../ui/StatusDot';
import { CitySummary } from '../../types/api';

interface HeaderProps {
  cities: CitySummary[];
  selectedCityId: string;
  onSelectCity: (cityId: string) => void;
  wsStatus: 'idle' | 'connecting' | 'open' | 'closed' | 'error';
  isBackendHealthy: boolean | null;
}

export const Header: React.FC<HeaderProps> = ({
  cities,
  selectedCityId,
  onSelectCity,
  wsStatus,
  isBackendHealthy,
}) => {
  const getStatusVariant = (): StatusVariant => {
    if (wsStatus === 'open' && isBackendHealthy) return 'online';
    if (wsStatus === 'connecting') return 'connecting';
    if (wsStatus === 'error' || isBackendHealthy === false) return 'critical';
    return 'offline';
  };

  const getStatusLabel = (): string => {
    if (wsStatus === 'open' && isBackendHealthy) return 'STREAM ACTIVE';
    if (wsStatus === 'connecting') return 'CONNECTING';
    if (isBackendHealthy === false) return 'BACKEND OFFLINE';
    if (wsStatus === 'error') return 'STREAM ERROR';
    return 'STANDBY';
  };

  return (
    <header className="bg-white border-b border-border transition-all">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-4">
        {/* Brand Identity - matching screenshot */}
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-[#08090c] flex items-center justify-center text-white shrink-0 shadow-sm">
            <ShieldAlert size={22} className="text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-heading text-lg font-bold tracking-tight text-text-primary">
                The 72-Hour Warning
              </span>
              <span className="bg-[#e5e1d5] border border-[#cfc9b8] text-text-secondary font-mono text-[10px] px-2 py-0.5 rounded font-bold uppercase tracking-wider">
                EOC INTEL
              </span>
            </div>
            <p className="text-xs text-text-muted">
              Cascading Urban Crisis Prediction & Decision Support
            </p>
          </div>
        </div>

        {/* Global Controls & Status - matching screenshot */}
        <div className="flex items-center gap-3">
          {/* Region Dropdown Selector */}
          <div className="relative">
            <div className="bg-navy text-white px-3 py-1.5 rounded-lg flex items-center gap-2 border border-navy shadow-sm cursor-pointer hover:bg-navy-deep transition-colors">
              <Globe size={14} className="text-risk-watch shrink-0" />
              <select
                aria-label="Select Target Region"
                value={selectedCityId}
                onChange={(e) => onSelectCity(e.target.value)}
                className="bg-transparent text-xs font-mono font-semibold tracking-wider text-white uppercase focus:outline-none cursor-pointer pr-4 appearance-none"
              >
                {cities.length > 0 ? (
                  cities.map((c) => (
                    <option key={c.city_id} value={c.city_id} className="bg-navy-deep text-white">
                      {c.city_id.replace(/_/g, ' ').toUpperCase()}
                    </option>
                  ))
                ) : (
                  <option value={selectedCityId} className="bg-navy-deep text-white">
                    {selectedCityId.replace(/_/g, ' ').toUpperCase()}
                  </option>
                )}
              </select>
              <ChevronDown size={14} className="text-text-navy-muted pointer-events-none -ml-3" />
            </div>
          </div>

          {/* Status Badge */}
          <div className="bg-[#34351e] border border-[#565735] text-accent-gold px-3 py-1.5 rounded-full flex items-center gap-2 text-xs font-mono font-bold tracking-wider shadow-sm">
            <StatusDot status={getStatusVariant()} pulse={wsStatus === 'open'} />
            <span>{getStatusLabel()}</span>
          </div>
        </div>
      </div>
    </header>
  );
};
