import React, { useState, useMemo } from 'react';
import {
  LineChart,
  Clock,
  Info,
  Compass,
} from 'lucide-react';
import { Card } from '../ui/Card';
import { RiskBadge } from '../ui/RiskBadge';
import { SectionHeading } from '../ui/SectionHeading';
import { Tooltip } from '../ui/Tooltip';
import { useStream } from '../../context/StreamContext';
import { RiskState } from '../../types/api';
import { formatLocalTime, formatPercent, formatUtcTime, RISK_STATE_CONFIG } from '../../lib/formatters';

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

export const ForecastsPage: React.FC = () => {
  const { latestForecast, currentConfig } = useStream();

  const [selectedHorizon, setSelectedHorizon] = useState<string>('24');
  const [selectedMetricType, setSelectedMetricType] = useState<'p_by' | 'p_at'>('p_by');
  const [selectedZoneId] = useState<string>('city');

  // Available horizons from forecast
  const horizons = useMemo(() => {
    if (latestForecast?.city_probabilities) {
      return Object.keys(latestForecast.city_probabilities).sort((a, b) => Number(a) - Number(b));
    }
    return ['1', '3', '6', '12', '24', '48', '72'];
  }, [latestForecast]);

  React.useEffect(() => {
    if (horizons.length > 0 && !horizons.includes(selectedHorizon)) {
      setSelectedHorizon(horizons[Math.min(4, horizons.length - 1)]);
    }
  }, [horizons, selectedHorizon]);

  // Probabilities at selected horizon
  const currentProbabilities = useMemo(() => {
    if (!latestForecast) return null;
    if (selectedZoneId === 'city') {
      return latestForecast.city_probabilities?.[selectedHorizon] || null;
    }
    return latestForecast.zone_probabilities?.[selectedZoneId]?.[selectedHorizon] || null;
  }, [latestForecast, selectedZoneId, selectedHorizon]);

  return (
    <div className="space-y-6">
      <SectionHeading
        title="Probabilistic Multi-Horizon Forecasts"
        subtitle="Cumulative (p_by) vs instantaneous (p_at) risk states and time-to-critical quantiles"
        icon={<LineChart size={18} className="text-text-primary" />}
      />

      {/* Forecast Meta & Calibration Banner */}
      <Card variant="cream" className="p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className="text-xs font-mono uppercase bg-white border border-border text-text-primary px-2 py-0.5 rounded font-bold">
                Monte Carlo 72-Hour Outlook
              </span>
              <span
                className={`text-xs font-mono px-2 py-0.5 rounded border font-bold ${
                  latestForecast?.calibrated
                    ? 'bg-risk-normal/15 text-risk-normal border-risk-normal/40'
                    : 'bg-risk-high/15 text-text-primary border-risk-high/40'
                }`}
              >
                {latestForecast?.calibrated ? 'Isotonic Calibrated' : 'Raw Rollout (Uncalibrated)'}
              </span>
              {latestForecast?.oracle && (
                <span className="text-xs font-mono bg-risk-watch/15 text-navy border border-risk-watch/40 px-2 py-0.5 rounded font-bold">
                  Oracle Rain Feed Active
                </span>
              )}
            </div>

            <h2 className="font-heading text-xl sm:text-2xl font-bold text-text-primary">
              Multi-Horizon Probabilistic Risk Distribution
            </h2>
            <p className="text-xs sm:text-sm text-text-secondary mt-1 font-mono">
              Issued at:{' '}
              <span className="font-bold text-navy">
                {latestForecast ? formatLocalTime(latestForecast.issued_at) : 'Awaiting engine run...'}
              </span>{' '}
              ({latestForecast ? formatUtcTime(latestForecast.issued_at) : ''})
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="bg-white p-3 rounded-lg border border-border text-right shadow-sm">
              <span className="text-[11px] font-mono text-text-muted block">REGIONAL STATE</span>
              <RiskBadge state={latestForecast?.city_risk_state || 'NORMAL'} size="md" />
            </div>
          </div>
        </div>
      </Card>

      {/* Probability Semantic Selector: p_by vs p_at */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Card variant="cream" className="md:col-span-2 p-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-heading text-base font-bold text-text-primary">
                  State Probability Evolution
                </h3>
                <Tooltip
                  content={
                    <div className="space-y-1">
                      <p className="font-semibold text-white">Probability Semantics:</p>
                      <p>
                        <strong>p_by:</strong> Cumulative probability of reaching threshold at <em>any time by hour H</em>.
                      </p>
                      <p>
                        <strong>p_at:</strong> Instantaneous probability of exceeding threshold <em>at exact hour H</em>.
                      </p>
                    </div>
                  }
                >
                  <Info size={14} className="text-text-muted cursor-help" />
                </Tooltip>
              </div>
              <p className="text-xs text-text-muted mt-0.5">
                Evaluated across multi-horizon steps (+1h to +72h)
              </p>
            </div>

            {/* Metric Mode Toggle */}
            <div className="flex bg-surface-muted p-1 rounded-lg border border-border self-start sm:self-center">
              <button
                type="button"
                onClick={() => setSelectedMetricType('p_by')}
                className={`px-3 py-1 text-xs font-mono rounded font-semibold transition-all ${
                  selectedMetricType === 'p_by'
                    ? 'bg-white text-text-primary border border-border shadow-sm'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                p_by (Cumulative)
              </button>
              <button
                type="button"
                onClick={() => setSelectedMetricType('p_at')}
                className={`px-3 py-1 text-xs font-mono rounded font-semibold transition-all ${
                  selectedMetricType === 'p_at'
                    ? 'bg-white text-text-primary border border-border shadow-sm'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                p_at (Instantaneous)
              </button>
            </div>
          </div>

          {/* Horizon Selection Buttons */}
          <div className="flex flex-wrap gap-2 mb-6">
            <span className="text-xs font-mono text-text-muted self-center mr-1">Horizon:</span>
            {horizons.map((h) => {
              const isSelected = selectedHorizon === h;
              return (
                <button
                  key={h}
                  type="button"
                  onClick={() => setSelectedHorizon(h)}
                  className={`px-3 py-1.5 rounded-lg border text-xs font-mono font-bold transition-all ${
                    isSelected
                      ? 'bg-navy text-white border-navy shadow-sm'
                      : 'bg-white text-text-secondary border-border hover:text-text-primary'
                  }`}
                >
                  +{h}h
                </button>
              );
            })}
          </div>

          {/* Probabilities Bars at Current Horizon */}
          <div className="space-y-4 pt-2">
            {(['NORMAL', 'WATCH', 'HIGH_RISK', 'CRITICAL'] as RiskState[]).map((state) => {
              const prob = currentProbabilities?.[state] ?? 0;
              const cfg = RISK_STATE_CONFIG[state];
              return (
                <div key={state} className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <div className="flex items-center gap-2">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: cfg.colorHex }}
                      />
                      <span className="font-bold text-text-primary">{cfg.label}</span>
                    </div>
                    <span className="font-bold tabular-nums text-text-primary text-sm">
                      {formatPercent(prob)}
                    </span>
                  </div>

                  {/* Visual Bar */}
                  <div className="h-2.5 w-full bg-surface-muted rounded-full overflow-hidden p-0.5 border border-border">
                    <div
                      className="h-full rounded-full transition-all duration-300"
                      style={{
                        width: `${Math.max(2, Math.min(100, prob * 100))}%`,
                        backgroundColor: cfg.colorHex,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* Time-To-Critical Quantile Distribution */}
        <Card variant="navy" className="p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3 pb-2 border-b border-[#1e2c4f]">
              <h3 className="font-heading text-base font-bold text-white">
                Time-to-Critical (TTC)
              </h3>
              <Clock size={16} className="text-risk-watch" />
            </div>
            <p className="text-xs text-text-navy-muted">
              First-passage time distribution across rollouts. Stated as an uncertainty interval, never a guaranteed countdown.
            </p>

            <div className="mt-5 space-y-3 font-mono">
              <div className="p-3 rounded-lg bg-navy-card border border-[#1e2c4f]">
                <span className="text-[11px] text-text-navy-muted block">P10 (EARLIEST IMPACT)</span>
                <span className="text-lg font-bold text-risk-watch tabular-nums">
                  {latestForecast?.cascade_summary?.[0]?.eta_p10 !== null &&
                  latestForecast?.cascade_summary?.[0]?.eta_p10 !== undefined
                    ? `+${latestForecast.cascade_summary[0].eta_p10.toFixed(1)} hours`
                    : 'No critical within 72h'}
                </span>
              </div>

              <div className="p-3 rounded-lg bg-navy-card border border-accent-gold shadow-sm">
                <span className="text-[11px] text-accent-gold font-bold block">
                  P50 (MEDIAN ESTIMATE)
                </span>
                <span className="text-xl font-bold text-white tabular-nums">
                  {latestForecast?.cascade_summary?.[0]?.eta_p50 !== null &&
                  latestForecast?.cascade_summary?.[0]?.eta_p50 !== undefined
                    ? `+${latestForecast.cascade_summary[0].eta_p50.toFixed(1)} hours`
                    : 'Mass censored (>72h)'}
                </span>
              </div>

              <div className="p-3 rounded-lg bg-navy-card border border-[#1e2c4f]">
                <span className="text-[11px] text-text-navy-muted block">P90 (UPPER BOUND)</span>
                <span className="text-lg font-bold text-risk-high tabular-nums">
                  {latestForecast?.cascade_summary?.[0]?.eta_p90 !== null &&
                  latestForecast?.cascade_summary?.[0]?.eta_p90 !== undefined
                    ? `+${latestForecast.cascade_summary[0].eta_p90.toFixed(1)} hours`
                    : 'Extended safety margin'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#1e2c4f] text-[11px] text-text-navy-muted">
            <span className="font-semibold text-white">Censoring Disclosure:</span> Rollouts where stress never crosses 0.8 critical threshold are explicitly bounded rather than imputed.
          </div>
        </Card>
      </div>

      {/* Zone-by-Zone Forecast Matrix */}
      <Card variant="cream" className="p-5">
        <SectionHeading
          title="Zone Risk Horizons"
          subtitle="Forecast risk state and probabilities at selected horizon"
          icon={<Compass size={16} className="text-text-primary" />}
        />

        <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3 w-full">
          {currentConfig?.zones.map((zone) => {
            const zState: RiskState | null = latestForecast?.zone_risk_states?.[zone.id] || null;
            const zProbs = latestForecast?.zone_probabilities?.[zone.id]?.[selectedHorizon];
            const hasProbs = zProbs !== undefined && zProbs !== null;
            const critProb = hasProbs ? zProbs['CRITICAL'] : null;
            const highProb = hasProbs ? zProbs['HIGH_RISK'] : null;

            return (
              <div
                key={zone.id}
                className="p-3.5 rounded-lg bg-white border border-border hover:border-navy transition-colors flex flex-col justify-between min-w-0"
              >
                <div className="flex items-start justify-between gap-2.5 min-w-0">
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-bold text-text-primary break-words [overflow-wrap:anywhere]" title={zone.name}>{zone.name}</h4>
                    <p className="text-[11px] font-mono text-text-muted break-words [overflow-wrap:anywhere]" title={zone.id}>
                      {renderIdentifierWithBreaks(zone.id)}
                    </p>
                  </div>
                  <RiskBadge state={zState} size="sm" className="shrink-0" />
                </div>

                <div className="mt-3 pt-3 border-t border-border/60 grid grid-cols-2 gap-2 text-xs font-mono">
                  <div>
                    <span className="text-[10px] text-text-muted block">
                      {selectedMetricType === 'p_by' ? 'P_BY(CRITICAL)' : 'P_AT(CRITICAL)'}
                    </span>
                    <span className="font-bold text-risk-critical">
                      {critProb !== null && critProb !== undefined ? formatPercent(critProb) : 'Awaiting data'}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-text-muted block">
                      {selectedMetricType === 'p_by' ? 'P_BY(HIGH RISK)' : 'P_AT(HIGH RISK)'}
                    </span>
                    <span className="font-bold text-risk-high">
                      {highProb !== null && highProb !== undefined ? formatPercent(highProb) : 'Awaiting data'}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
};
