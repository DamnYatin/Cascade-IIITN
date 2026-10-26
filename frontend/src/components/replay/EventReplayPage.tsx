import React, { useState } from 'react';
import {
  RotateCcw,
  Zap,
  Clock,
  Bug,
} from 'lucide-react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { SectionHeading } from '../ui/SectionHeading';
import { submitFault } from '../../lib/api';
import { useStream } from '../../context/StreamContext';
import { FaultInput } from '../../types/api';
import { formatLocalTime, formatUtcTime } from '../../lib/formatters';

export const EventReplayPage: React.FC = () => {
  const {
    cities,
    selectedCityId,
    setSelectedCityId,
    streamConfig,
    updateStreamConfig,
    clockTime,
    displayedStatus,
    activeFaults,
    currentConfig,
    connectStream,
    disconnectStream,
    reconnectStream,
  } = useStream();

  // Fault Injection form state
  const [faultKind, setFaultKind] = useState<string>('dropout');
  const [targetZone, setTargetZone] = useState<string>('');
  const [targetSystem, setTargetSystem] = useState<string>('');
  const [delayHours, setDelayHours] = useState<number>(3.0);
  const [spikeMagnitude, setSpikeMagnitude] = useState<number>(10.0);
  const [stuckValue, setStuckValue] = useState<number>(0.0);
  const [isSubmittingFault, setIsSubmittingFault] = useState<boolean>(false);
  const [faultMessage, setFaultMessage] = useState<{ text: string; ok: boolean } | null>(null);

  const speedOptions = [0.5, 1.0, 2.0, 5.0, 10.0];
  const rainWindows = ['peak', 'onset', 'receding', 'hero_full', 'none'];

  const handleInjectFault = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmittingFault(true);
    setFaultMessage(null);

    const faultPayload: FaultInput = {
      kind: faultKind,
      target_zone: targetZone || undefined,
      target_system: targetSystem || undefined,
      start_hour: 0,
      end_hour: 1000000,
      probability: 0.5,
      delay_hours: delayHours,
      stuck_value: stuckValue,
      spike_magnitude: spikeMagnitude,
      burst_count: 20,
    };

    try {
      const res = await submitFault({
        city: streamConfig.city,
        seed: streamConfig.seed,
        fault: faultPayload,
      });
      setFaultMessage({
        text: `Injected fault '${res.fault}' into session (${res.fault_log_entries} active in log).`,
        ok: true,
      });
    } catch (err: any) {
      setFaultMessage({
        text: err?.message || 'Fault injection failed',
        ok: false,
      });
    } finally {
      setIsSubmittingFault(false);
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeading
        title="Event Replay & Chaos Injection"
        subtitle="Control replay clock parameters and inject synthetic sensor faults via POST /faults"
        icon={<RotateCcw size={18} className="text-text-primary" />}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Replay Stream Controls */}
        <Card variant="cream" className="lg:col-span-2 p-5 space-y-6">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <div>
              <h3 className="font-heading text-base font-bold text-text-primary">
                Replay Stream Parameters
              </h3>
              <p className="text-xs text-text-muted mt-0.5">
                Parameters passed to WebSocket query string: /ws/stream
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-text-muted">Status:</span>
              <span className="text-xs font-mono font-bold text-navy uppercase truncate max-w-[200px]" title={displayedStatus.label}>
                {displayedStatus.label}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* City Selection */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1.5">
                TARGET REGION / CITY
              </label>
              <select
                value={selectedCityId}
                onChange={(e) => {
                  setSelectedCityId(e.target.value);
                  updateStreamConfig({ city: e.target.value });
                }}
                className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary focus:outline-none focus:border-navy"
              >
                {cities.map((c) => (
                  <option key={c.city_id} value={c.city_id}>
                    {c.city_id.toUpperCase()} ({c.zones} zones)
                  </option>
                ))}
              </select>
            </div>

            {/* Seed */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1.5">
                RNG SEED (REPRODUCIBLE SIMULATION)
              </label>
              <input
                type="number"
                value={streamConfig.seed}
                onChange={(e) => updateStreamConfig({ seed: parseInt(e.target.value) || 1 })}
                className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary font-mono focus:outline-none focus:border-navy"
              />
            </div>

            {/* Replay Speed */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1.5">
                CLOCK ACCELERATION SPEED
              </label>
              <div className="flex gap-1.5">
                {speedOptions.map((spd) => (
                  <button
                    key={spd}
                    type="button"
                    onClick={() => updateStreamConfig({ speed: spd })}
                    className={`flex-1 py-1.5 text-xs font-mono rounded font-bold transition-all ${
                      streamConfig.speed === spd
                        ? 'bg-navy text-white border border-navy shadow-sm'
                        : 'bg-white text-text-secondary border border-border hover:text-text-primary'
                    }`}
                  >
                    {spd}x
                  </button>
                ))}
              </div>
            </div>

            {/* Rain Window */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1.5">
                ASSAM 2026 SCENARIO RAIN WINDOW
              </label>
              <select
                value={streamConfig.rain_window}
                onChange={(e) => updateStreamConfig({ rain_window: e.target.value })}
                className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary focus:outline-none focus:border-navy"
              >
                {rainWindows.map((rw) => (
                  <option key={rw} value={rw}>
                    {rw.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>

            {/* Duration Hours */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1.5">
                MAX DURATION (HOURS)
              </label>
              <input
                type="number"
                min="1"
                max="168"
                value={streamConfig.hours}
                onChange={(e) => updateStreamConfig({ hours: parseInt(e.target.value) || 72 })}
                className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary font-mono focus:outline-none focus:border-navy"
              />
            </div>

            {/* Anchor Mode */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1.5">
                ANCHOR MODE (GROUND TRUTH COUPLING)
              </label>
              <select
                value={streamConfig.anchor}
                onChange={(e) => updateStreamConfig({ anchor: e.target.value })}
                className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary focus:outline-none focus:border-navy"
              >
                <option value="off">OFF (Nominal Uncoupled)</option>
                <option value="on">ON (Anchored Real)</option>
              </select>
            </div>
          </div>

          <div className="pt-3 border-t border-border flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <p className="text-xs text-text-muted">
              Applying changes creates a new deterministic ReplaySession in memory.
            </p>
            <div className="flex items-center gap-2">
              {displayedStatus.buttonState === 'disconnect' && (
                <Button
                  variant="outline"
                  size="md"
                  onClick={disconnectStream}
                >
                  Disconnect
                </Button>
              )}
              <Button
                variant="primary"
                size="md"
                icon={<RotateCcw size={14} className={displayedStatus.isConnecting ? 'animate-spin' : ''} />}
                disabled={displayedStatus.isConnecting}
                onClick={reconnectStream}
              >
                Restart Stream with Parameters
              </Button>
            </div>
          </div>
        </Card>

        {/* Live Replay Clock Telemetry */}
        <Card variant="navy" className="p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-[#1e2c4f]">
              <h3 className="font-heading text-base font-bold text-white">
                Clock Telemetry
              </h3>
              <Clock size={16} className="text-risk-watch" />
            </div>

            <div className="mt-4 space-y-4">
              <div className="p-3.5 rounded-lg bg-navy-card border border-[#1e2c4f]">
                <span className="text-[11px] font-mono text-text-navy-muted block">CURRENT CLOCK TIME</span>
                <span className="text-xl font-bold font-mono text-white tabular-nums">
                  {clockTime ? formatLocalTime(clockTime) : 'Awaiting sync...'}
                </span>
                <span className="text-[11px] font-mono text-text-navy-muted block mt-0.5">
                  UTC: {formatUtcTime(clockTime)}
                </span>
              </div>

              <div className="p-3.5 rounded-lg bg-navy-card border border-[#1e2c4f]">
                <span className="text-[11px] font-mono text-text-navy-muted block">CONFIG START TIME</span>
                <span className="text-sm font-bold font-mono text-white tabular-nums">
                  {currentConfig ? formatLocalTime(currentConfig.start_time_utc) : '—'}
                </span>
              </div>

              {/* Active Faults Tag Cloud */}
              <div>
                <span className="text-xs font-mono text-text-navy-muted block mb-1.5">
                  ACTIVE FAULTS APPLIED IN SESSION:
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {activeFaults.length > 0 ? (
                    activeFaults.map((flt, idx) => (
                      <span
                        key={idx}
                        className="text-xs font-mono px-2 py-0.5 rounded bg-risk-critical/20 text-white border border-risk-critical"
                      >
                        {flt}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-text-navy-muted">No faults currently active</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 text-[11px] text-text-navy-muted">
            <span className="font-semibold text-white">Future Isolation:</span> Replay harness enforces strict arrival_time ≤ clock release invariant.
          </div>
        </Card>
      </div>

      {/* Fault Injection Panel */}
      <Card variant="cream" className="p-5">
        <SectionHeading
          title="Chaos Fault Injector (POST /faults)"
          subtitle="Directly inject adversarial perturbations into the active stream session to test system resilience"
          icon={<Bug size={18} className="text-text-primary" />}
        />

        <form onSubmit={handleInjectFault} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Fault Kind */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1">
                FAULT KIND
              </label>
              <select
                value={faultKind}
                onChange={(e) => setFaultKind(e.target.value)}
                className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary focus:outline-none focus:border-navy"
              >
                <option value="dropout">Dropout (Zero-out sensor)</option>
                <option value="stuck_at">Stuck-At (Constant freeze)</option>
                <option value="spike">Spike (Additive anomaly)</option>
                <option value="feed_delay">Feed Delay (Out-of-order latency)</option>
                <option value="contradictory_duplicate">Contradictory Duplicate</option>
                <option value="citizen_spam">Citizen Spam Burst</option>
                <option value="blackout">Zone Blackout</option>
              </select>
            </div>

            {/* Target Zone */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1">
                TARGET ZONE (OPTIONAL)
              </label>
              <select
                value={targetZone}
                onChange={(e) => setTargetZone(e.target.value)}
                className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary focus:outline-none focus:border-navy"
              >
                <option value="">All Zones (Broadcast)</option>
                {currentConfig?.zones.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.name} ({z.id})
                  </option>
                ))}
              </select>
            </div>

            {/* Target System */}
            <div>
              <label className="text-xs font-mono font-semibold text-text-secondary block mb-1">
                TARGET SYSTEM (OPTIONAL)
              </label>
              <select
                value={targetSystem}
                onChange={(e) => setTargetSystem(e.target.value)}
                className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary focus:outline-none focus:border-navy"
              >
                <option value="">All Systems</option>
                {currentConfig?.systems.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.id.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>

            {/* Parameter Adjustment */}
            {faultKind === 'feed_delay' && (
              <div>
                <label className="text-xs font-mono font-semibold text-text-secondary block mb-1">
                  DELAY HOURS
                </label>
                <input
                  type="number"
                  step="0.5"
                  value={delayHours}
                  onChange={(e) => setDelayHours(parseFloat(e.target.value) || 2.0)}
                  className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary font-mono focus:outline-none focus:border-navy"
                />
              </div>
            )}

            {faultKind === 'spike' && (
              <div>
                <label className="text-xs font-mono font-semibold text-text-secondary block mb-1">
                  SPIKE MAGNITUDE
                </label>
                <input
                  type="number"
                  step="1"
                  value={spikeMagnitude}
                  onChange={(e) => setSpikeMagnitude(parseFloat(e.target.value) || 10.0)}
                  className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary font-mono focus:outline-none focus:border-navy"
                />
              </div>
            )}

            {faultKind === 'stuck_at' && (
              <div>
                <label className="text-xs font-mono font-semibold text-text-secondary block mb-1">
                  STUCK CONSTANT VALUE
                </label>
                <input
                  type="number"
                  step="0.1"
                  value={stuckValue}
                  onChange={(e) => setStuckValue(parseFloat(e.target.value) || 0.0)}
                  className="w-full bg-white text-xs px-3 py-2 rounded-lg border border-border text-text-primary font-mono focus:outline-none focus:border-navy"
                />
              </div>
            )}
          </div>

          <div className="flex items-center justify-between pt-2">
            <div>
              {faultMessage && (
                <span
                  className={`text-xs font-mono font-bold ${
                    faultMessage.ok ? 'text-navy' : 'text-risk-critical'
                  }`}
                >
                  {faultMessage.text}
                </span>
              )}
            </div>
            <Button
              type="submit"
              variant="danger"
              size="md"
              isLoading={isSubmittingFault}
              icon={<Zap size={14} />}
            >
              Inject Fault into Session
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
};
