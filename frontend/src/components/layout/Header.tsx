import React, { useState, useEffect } from 'react';
import { ShieldAlert, Globe, ChevronDown, Play, Square, RefreshCw } from 'lucide-react';
import { StatusDot, StatusVariant } from '../ui/StatusDot';
import { Button } from '../ui/Button';
import { CitySummary } from '../../types/api';
import { useStream } from '../../context/StreamContext';

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
}) => {
  const {
    displayedStatus,
    connectStream,
    disconnectStream,
    reconnectStream,
  } = useStream();

  const [announcement, setAnnouncement] = useState<string>('');

  // Announce connection state changes politely to screen readers
  useEffect(() => {
    setAnnouncement(`Stream status: ${displayedStatus.label}`);
  }, [displayedStatus.label]);

  const handleConnectionAction = () => {
    if (displayedStatus.buttonState === 'disconnect') {
      disconnectStream();
    } else if (displayedStatus.buttonState === 'retry') {
      reconnectStream();
    } else {
      connectStream();
    }
  };

  const mapVariantToStatusVariant = (variant: string): StatusVariant => {
    if (variant === 'online') return 'online';
    if (variant === 'connecting') return 'connecting';
    if (variant === 'critical') return 'critical';
    return 'offline';
  };

  return (
    <header className="bg-white border-b border-border transition-all">
      {/* Polite live region for accessibility */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-4">
        {/* Brand Identity */}
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

        {/* Global Controls & Status */}
        <div className="flex items-center gap-2.5">
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

          {/* Interactive Connect / Disconnect Action Button */}
          <Button
            size="sm"
            variant={displayedStatus.buttonState === 'disconnect' ? 'outline' : 'primary'}
            disabled={displayedStatus.isConnecting}
            onClick={handleConnectionAction}
            className="text-xs h-[34px] px-3 font-mono font-bold whitespace-nowrap"
            icon={
              displayedStatus.buttonState === 'disconnect' ? (
                <Square size={12} className="fill-current" />
              ) : displayedStatus.buttonState === 'retry' ? (
                <RefreshCw size={12} className={displayedStatus.isConnecting ? 'animate-spin' : ''} />
              ) : (
                <Play size={12} className="fill-current" />
              )
            }
          >
            {displayedStatus.buttonLabel}
          </Button>

          {/* Status Badge */}
          <div
            className={`px-3 py-1.5 rounded-full flex items-center gap-2 text-xs font-mono font-bold tracking-wider shadow-sm border transition-all ${displayedStatus.badgeClass}`}
            role="status"
            aria-label={displayedStatus.statusAriaLabel}
          >
            <StatusDot
              status={mapVariantToStatusVariant(displayedStatus.variant)}
              pulse={displayedStatus.pulse}
            />
            <span className="whitespace-nowrap">{displayedStatus.label}</span>
          </div>
        </div>
      </div>
    </header>
  );
};
