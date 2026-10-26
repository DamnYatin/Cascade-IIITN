import React from 'react';
import { Link } from 'react-router-dom';
import {
  Clock,
  AlertTriangle,
  Network,
  ArrowRight,
  CheckCircle2,
  Layers,
  ChevronRight,
} from 'lucide-react';
import { Card } from '../ui/Card';
import { RiskBadge } from '../ui/RiskBadge';
import { SectionHeading } from '../ui/SectionHeading';
import { useStream } from '../../context/StreamContext';
import {
  formatDuration,
  formatLocalTime,
  formatPercent,
  getLatencyMinutes,
  RISK_STATE_CONFIG,
} from '../../lib/formatters';
import { RiskState } from '../../types/api';

function renderIdentifierWithBreaks(text: string | null | undefined) {
  if (!text) return text;
  const parts = text.split('_');
  return parts.map((part, index) => (
    <React.Fragment key={index}>
      {part}
      {index < parts.length - 1 && (
        <>
          _<wbr />
        </>
      )}
    </React.Fragment>
  ));
}

export const OverviewPage: React.FC = () => {
  const {
    currentConfig,
    latestForecast,
    clockTime,
    displayedStatus,
    isBackendHealthy,
    selectedCityId,
  } = useStream();

  // Aggregate zone risk states
  const totalZones = currentConfig?.zones.length || 0;
  const riskCounts: Record<RiskState, number> = {
    NORMAL: 0,
    WATCH: 0,
    HIGH_RISK: 0,
    CRITICAL: 0,
  };
  let diagnosedZonesCount = 0;

  if (latestForecast?.zone_risk_states) {
    Object.values(latestForecast.zone_risk_states).forEach((state) => {
      if (state in riskCounts) {
        riskCounts[state as RiskState]++;
        diagnosedZonesCount++;
      }
    });
  }

  const unforecastedCount = Math.max(0, totalZones - diagnosedZonesCount);
  const cityRiskState: RiskState | null = latestForecast?.city_risk_state || null;

  // Identify elevated / critical zones
  const criticalZones = latestForecast?.zone_risk_states
    ? Object.entries(latestForecast.zone_risk_states)
        .filter(([_, state]) => state === 'CRITICAL' || state === 'HIGH_RISK' || state === 'WATCH')
        .map(([zoneId, state]) => ({ zoneId, state }))
    : [];

  const getTimelineClockDisplay = () => {
    if (clockTime) return formatLocalTime(clockTime);
    return displayedStatus.label;
  };

  return (
    <div className="space-y-6">
      {/* Hero Section matching the reference screenshot */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Left Hero Card (Cream) */}
        <Card variant="cream" className="lg:col-span-2 p-6 flex flex-col justify-between">
          <div>
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
              <div>
                <h1 className="font-heading text-2xl sm:text-3xl lg:text-[34px] font-extrabold tracking-tight text-text-primary leading-[1.18] uppercase">
                  <span className="marker-gold">CASCADING CRISIS</span>
                  <br />
                  <span className="marker-gold">EARLY WARNING</span>
                </h1>
                <p className="text-xs sm:text-sm text-text-secondary mt-3 max-w-xl leading-relaxed">
                  Continuous probabilistic hazard propagation across municipal and emergency
                  services.{' '}
                  <span className="marker-gold-sm font-semibold text-text-primary">
                    Evaluated against the Assam monsoon 2026 hero flood scenario.
                  </span>
                </p>
              </div>

              {/* Regional Status Navy Pill Box (top-right inside left card) */}
              <div className="bg-navy-deep p-3 rounded-xl border border-[#1e2c4f] flex flex-col gap-1 items-start shrink-0 min-w-[125px] shadow-sm">
                <span className="text-[10px] font-mono tracking-wider font-semibold text-risk-watch uppercase">
                  REGIONAL STATUS
                </span>
                <RiskBadge state={cityRiskState} size="sm" />
                <span className="text-[11px] font-mono font-bold text-accent-gold uppercase tracking-wider mt-0.5">
                  {selectedCityId.toUpperCase()}
                </span>
              </div>
            </div>
          </div>

          {/* Statistics Row at bottom of left card */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6 pt-5 border-t border-border">
            <div>
              <p className="text-[10px] text-text-muted uppercase font-mono tracking-wider">
                ZONES MONITORED
              </p>
              <p className="text-2xl font-bold font-mono text-text-primary mt-0.5 tabular-nums">
                {totalZones > 0 ? totalZones : '—'}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-text-muted uppercase font-mono tracking-wider">
                SYSTEMS COUPLED
              </p>
              <p className="text-2xl font-bold font-mono text-text-primary mt-0.5 tabular-nums">
                {currentConfig?.systems.length || '—'}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-text-muted uppercase font-mono tracking-wider">
                STREAM STATUS
              </p>
              <div className="mt-0.5">
                <span className="marker-gold-sm font-bold font-mono text-text-primary uppercase text-lg">
                  {displayedStatus.label}
                </span>
              </div>
            </div>
            <div>
              <p className="text-[10px] text-text-muted uppercase font-mono tracking-wider">
                CALIBRATION
              </p>
              <div className="mt-0.5">
                <span className="marker-gold-sm font-bold font-mono text-text-primary text-base leading-snug">
                  {latestForecast?.calibrated ? 'Isotonic Calibrated' : 'Raw Rollout (Uncalibrated)'}
                </span>
              </div>
            </div>
          </div>
        </Card>

        {/* Right Hero Card: Replay Timeline (Navy) */}
        <Card variant="navy" className="p-6 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-[#1e2c4f]">
              <span className="text-xs font-mono tracking-wider text-risk-watch uppercase font-semibold">
                REPLAY TIMELINE
              </span>
              <Clock size={16} className="text-risk-watch" />
            </div>

            <div className="mt-4">
              <p className="text-2xl font-bold font-mono text-white tracking-wide tabular-nums">
                {getTimelineClockDisplay()}
              </p>
              <p className="text-xs text-text-navy-muted font-mono mt-1">
                Started: {currentConfig ? formatLocalTime(currentConfig.start_time_utc) : '5 Jul, 05:30:00'}
              </p>
            </div>

            <div className="mt-5 space-y-2.5 text-xs font-mono">
              <div className="flex justify-between items-center">
                <span className="text-text-navy-muted">Backend FastAPI:</span>
                <span className="text-accent-gold font-bold">
                  {isBackendHealthy ? 'ONLINE (Port 8000)' : 'UNREACHABLE'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-text-navy-muted">Evidence Quality (City):</span>
                <span className="text-white">
                  {latestForecast?.evidence_quality?.city !== undefined
                    ? formatPercent(latestForecast.evidence_quality.city)
                    : '—'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-text-navy-muted">Learned Edges:</span>
                <span className="text-accent-gold font-bold">
                  {latestForecast?.top_edges?.length ? `${latestForecast.top_edges.length} active` : 'Config prior only'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-6 pt-4 border-t border-[#1e2c4f]">
            <Link
              to="/operations"
              className="w-full bg-navy-deep hover:bg-[#152345] border border-accent-gold text-accent-gold font-mono text-xs font-bold py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 transition-colors uppercase tracking-wider min-h-[44px]"
            >
              <ArrowRight size={14} className="text-accent-gold" />
              <span>LAUNCH LIVE OPERATIONS</span>
            </Link>
          </div>
        </Card>
      </div>

      {/* 4 Risk-State Cards in a row matching the reference screenshot */}
      <div className="space-y-3">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {(['NORMAL', 'WATCH', 'HIGH_RISK', 'CRITICAL'] as RiskState[]).map((state) => {
            const count = riskCounts[state];
            const pct = totalZones > 0 ? Math.round((count / totalZones) * 100) : 0;
            return (
              <Card key={state} variant="navy" className="p-4">
                <div className="flex items-center justify-between">
                  <RiskBadge state={state} size="sm" />
                  <span className="text-xs font-mono text-text-navy-muted">Zones</span>
                </div>
                <div className="mt-4 flex items-baseline justify-between">
                  <span className="text-3xl font-bold font-mono tracking-tight text-white tabular-nums">
                    {count}
                  </span>
                  <span className="text-xs font-mono text-text-navy-muted">
                    {totalZones > 0 ? `${count}/${totalZones} (${pct}%)` : `${count} zones`}
                  </span>
                </div>
              </Card>
            );
          })}
        </div>

        {/* Explicit Honest Disclosure of Zones with No Forecast Yet */}
        {unforecastedCount > 0 && (
          <div className="bg-[#ede7d6] border border-border px-3.5 py-2 rounded-lg text-xs font-mono text-text-secondary flex items-center justify-between">
            <span>
              <strong>{unforecastedCount} of {totalZones} zones</strong> have no active forecast yet (counted as unpredicted, never as nominal).
            </span>
            <span className="text-[11px] uppercase font-bold text-text-muted">Awaiting first rollout</span>
          </div>
        )}
      </div>

      {/* Lower Panels: Elevated Risk Zones & Active Cascade Stages */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Elevated Risk Zones Panel */}
        <Card variant="cream" className="p-5 flex flex-col justify-between">
          <div>
            <SectionHeading
              title="Elevated Risk Zones"
              subtitle="Zones exhibiting elevated stress"
              icon={<AlertTriangle size={18} className="text-text-primary" />}
            />

            <div className="space-y-2.5 mt-3">
              {criticalZones.length > 0 ? (
                criticalZones.map(({ zoneId, state }) => {
                  const zoneObj = currentConfig?.zones.find((z) => z.id === zoneId);
                  const zoneName = zoneObj?.name || zoneId;
                  return (
                    <Link
                      to={`/cascade?zone=${encodeURIComponent(zoneId)}`}
                      key={zoneId}
                      className="p-3 rounded-lg bg-white border border-border flex items-center justify-between gap-3 hover:border-text-secondary transition-colors min-h-[44px] min-w-0"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-text-primary break-words [overflow-wrap:anywhere]">{zoneName}</p>
                        <p className="text-[11px] font-mono text-text-muted break-words [overflow-wrap:anywhere]">{zoneId}</p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <RiskBadge state={state} size="sm" />
                        <ChevronRight size={14} className="text-text-muted" />
                      </div>
                    </Link>
                  );
                })
              ) : (
                <div className="text-center py-8 text-text-muted">
                  <CheckCircle2 size={32} className="mx-auto text-risk-normal mb-2" />
                  <p className="text-xs font-mono">All monitored zones currently within nominal thresholds.</p>
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* Active Cascade Stages Panel */}
        <Card variant="cream" className="p-5 flex flex-col justify-between">
          <div>
            <SectionHeading
              title="Active Cascade Stages"
              subtitle="Highest-probability failure sequence discovered by Monte Carlo rollouts"
              icon={<Network size={18} className="text-text-primary" />}
              action={
                <Link
                  to="/cascade"
                  className="flex items-center gap-1 text-xs font-mono font-bold text-text-primary hover:text-navy hover:underline"
                >
                  <span>→ Explorer</span>
                </Link>
              }
            />

            {latestForecast?.cascade_summary && latestForecast.cascade_summary.length > 0 ? (
              <div className="space-y-3 mt-3">
                {latestForecast.cascade_summary.slice(0, 3).map((stg) => (
                  <div
                    key={`${stg.stage}-${stg.node}`}
                    className="p-3 rounded-lg bg-white border border-border flex items-center justify-between gap-3"
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <span className="h-6 w-6 rounded-md bg-surface-muted text-text-primary border border-border font-mono text-xs font-bold flex items-center justify-center shrink-0">
                        {stg.stage}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p
                          className="text-xs font-mono font-bold text-text-primary break-words [overflow-wrap:anywhere]"
                          title={stg.node}
                        >
                          {renderIdentifierWithBreaks(stg.node)}
                        </p>
                        <p className="text-[11px] text-text-muted truncate">
                          Driver:{' '}
                          <span className="font-mono text-text-secondary">
                            {stg.dominant_parent || 'Direct precipitation shock'}
                          </span>
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 text-xs font-mono shrink-0">
                      <div className="text-right">
                        <span className="text-[10px] text-text-muted block">PROB</span>
                        <span className="font-bold text-text-primary">
                          {formatPercent(stg.probability)}
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-[10px] text-text-muted block">MEDIAN ETA</span>
                        <span className="font-bold text-navy">
                          {stg.eta_p50 !== null && stg.eta_p50 !== undefined
                            ? `+${stg.eta_p50.toFixed(1)}h`
                            : '—'}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-text-muted">
                <Layers size={32} className="mx-auto text-text-muted/60 mb-2" />
                <p className="text-xs font-mono">No active cascade propagation sequence detected.</p>
              </div>
            )}
          </div>

          <div className="mt-4 pt-3 border-t border-border flex justify-between items-center text-xs text-text-muted font-mono">
            <span>Stage Sequence</span>
            <span className="font-bold">1 / 3</span>
          </div>
        </Card>
      </div>
    </div>
  );
};
