import React, { useState, useMemo } from 'react';
import {
  Radio,
  Search,
  Clock,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { SectionHeading } from '../ui/SectionHeading';
import { Tooltip } from '../ui/Tooltip';
import { useStream } from '../../context/StreamContext';
import {
  formatDuration,
  formatLocalTime,
  formatUtcTime,
  getLatencyMinutes,
  SOURCE_KIND_CONFIG,
} from '../../lib/formatters';

export const LiveOperationsPage: React.FC = () => {
  const {
    observations,
    totalObsCount,
    maxObservations,
    currentConfig,
    clockTime,
    displayedStatus,
    clearObservations,
    connectStream,
    disconnectStream,
    reconnectStream,
  } = useStream();

  const [selectedZone, setSelectedZone] = useState<string>('all');
  const [selectedSystem, setSelectedSystem] = useState<string>('all');
  const [selectedSourceKind, setSelectedSourceKind] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [showOnlyLate, setShowOnlyLate] = useState<boolean>(false);

  // Late threshold in minutes
  const LATENCY_THRESHOLD_MINUTES = 60;

  const filteredObservations = useMemo(() => {
    return observations.filter((obs) => {
      if (selectedZone !== 'all' && obs.zone !== selectedZone) return false;
      if (selectedSystem !== 'all' && obs.system !== selectedSystem) return false;
      if (selectedSourceKind !== 'all' && obs.source_kind !== selectedSourceKind) return false;

      const latency = getLatencyMinutes(obs.event_time, obs.arrival_time);
      if (showOnlyLate && latency < LATENCY_THRESHOLD_MINUTES) return false;

      if (searchTerm) {
        const q = searchTerm.toLowerCase();
        const matchesNode = (obs.node_id || `${obs.zone}:${obs.system}`).toLowerCase().includes(q);
        const matchesSource = obs.source.toLowerCase().includes(q);
        const matchesZone = obs.zone.toLowerCase().includes(q);
        const matchesFlags = obs.quality_flags.some((f) => f.toLowerCase().includes(q));
        if (!matchesNode && !matchesSource && !matchesZone && !matchesFlags) return false;
      }

      return true;
    });
  }, [observations, selectedZone, selectedSystem, selectedSourceKind, searchTerm, showOnlyLate]);

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Live Stream Operations"
        subtitle="Real-time multi-source observation ingest feed with latency tracking and quality verification"
        icon={<Radio size={18} className="text-text-primary" />}
      />

      {/* Top Telemetry & Stream Status */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card variant="navy" className="p-4">
          <p className="text-[10px] font-mono uppercase text-risk-watch tracking-wider">REPLAY CLOCK</p>
          <p className="text-xl font-bold font-mono text-white mt-1 tabular-nums">
            {clockTime ? formatLocalTime(clockTime) : 'Awaiting sync...'}
          </p>
          <p className="text-[11px] text-text-navy-muted font-mono mt-0.5">
            UTC: {formatUtcTime(clockTime)}
          </p>
        </Card>

        <Card variant="cream" className="p-4">
          <p className="text-[10px] font-mono uppercase text-text-muted tracking-wider">BUFFERED RECORDS</p>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-xl font-bold font-mono text-text-primary tabular-nums">
              {observations.length}
            </span>
            <span className="text-xs text-text-muted font-mono">
              / capped at {maxObservations}
            </span>
          </div>
          <p className="text-[11px] text-text-secondary mt-0.5 font-mono">
            Total Ingested: {totalObsCount}
          </p>
        </Card>

        <Card variant="cream" className="p-4">
          <p className="text-[10px] font-mono uppercase text-text-muted tracking-wider">LATENESS POLICY</p>
          <p className="text-base font-bold text-risk-high font-mono mt-1">
            &gt; {LATENCY_THRESHOLD_MINUTES} min threshold
          </p>
          <p className="text-[11px] text-text-muted mt-0.5">
            Arrival time − Event time delay
          </p>
        </Card>

        <Card variant="navy" className="p-4 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-mono uppercase text-text-navy-muted tracking-wider">STREAM STATUS</p>
            <span className="text-xs font-mono text-accent-gold font-bold uppercase truncate max-w-[140px]" title={displayedStatus.label}>
              {displayedStatus.label}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-2">
            {displayedStatus.buttonState === 'disconnect' ? (
              <Button
                size="sm"
                variant="outline"
                className="flex-1 py-1 text-xs text-white border-white/30 hover:bg-white/10"
                onClick={disconnectStream}
              >
                Disconnect
              </Button>
            ) : (
              <Button
                size="sm"
                variant="gold"
                className="flex-1 py-1 text-xs"
                icon={<RefreshCw size={12} className={displayedStatus.isConnecting ? 'animate-spin' : ''} />}
                disabled={displayedStatus.isConnecting}
                onClick={displayedStatus.buttonState === 'retry' ? reconnectStream : connectStream}
              >
                {displayedStatus.buttonLabel}
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              className="py-1 text-xs text-white border-white/30 hover:bg-white/10"
              icon={<Trash2 size={12} />}
              onClick={clearObservations}
              title="Clear current table buffer"
            >
              Clear
            </Button>
          </div>
        </Card>
      </div>

      {/* Filter Toolbar */}
      <Card variant="cream" className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5 flex-1 min-w-[280px]">
            {/* Search */}
            <div className="relative min-w-[180px] max-w-xs flex-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                type="text"
                placeholder="Search node, source, flag..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full bg-white text-xs pl-8 pr-3 py-1.5 rounded-lg border border-border text-text-primary placeholder-text-muted focus:outline-none focus:border-navy"
              />
            </div>

            {/* Zone Filter */}
            <select
              aria-label="Filter by Zone"
              value={selectedZone}
              onChange={(e) => setSelectedZone(e.target.value)}
              className="bg-white text-xs px-2.5 py-1.5 rounded-lg border border-border text-text-primary focus:outline-none"
            >
              <option value="all">All Zones</option>
              {currentConfig?.zones.map((z) => (
                <option key={z.id} value={z.id}>
                  {z.name} ({z.id})
                </option>
              ))}
            </select>

            {/* System Filter */}
            <select
              aria-label="Filter by System"
              value={selectedSystem}
              onChange={(e) => setSelectedSystem(e.target.value)}
              className="bg-white text-xs px-2.5 py-1.5 rounded-lg border border-border text-text-primary focus:outline-none"
            >
              <option value="all">All Systems</option>
              {currentConfig?.systems.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.id.toUpperCase()} ({s.unit})
                </option>
              ))}
            </select>

            {/* Source Kind Filter */}
            <select
              aria-label="Filter by Source Kind"
              value={selectedSourceKind}
              onChange={(e) => setSelectedSourceKind(e.target.value)}
              className="bg-white text-xs px-2.5 py-1.5 rounded-lg border border-border text-text-primary focus:outline-none"
            >
              <option value="all">All Source Kinds</option>
              <option value="real">Real Feeds</option>
              <option value="simulated">Simulated</option>
              <option value="disaggregated">Disaggregated</option>
            </select>

            {/* Late Toggle */}
            <button
              type="button"
              onClick={() => setShowOnlyLate(!showOnlyLate)}
              className={`text-xs px-3 py-1.5 rounded-lg border font-mono transition-colors ${
                showOnlyLate
                  ? 'bg-risk-high/20 text-navy-deep border-risk-high font-bold'
                  : 'bg-white text-text-secondary border-border hover:text-text-primary'
              }`}
            >
              {showOnlyLate ? '✓ Only Late (>60m)' : 'Filter Late'}
            </button>
          </div>

          <div className="text-xs font-mono text-text-muted">
            Displaying {filteredObservations.length} of {observations.length} buffered
          </div>
        </div>
      </Card>

      {/* Observation Feed Table */}
      <Card variant="cream" className="p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="bg-[#eee9da] border-b border-border text-text-muted font-mono uppercase text-[11px] sticky top-0">
              <tr>
                <th className="py-3 px-4">Node (Zone:System)</th>
                <th className="py-3 px-3">Source & Kind</th>
                <th className="py-3 px-3">Value</th>
                <th className="py-3 px-3">Event Time</th>
                <th className="py-3 px-3">Arrival Time</th>
                <th className="py-3 px-3">Delay (Latency)</th>
                <th className="py-3 px-4">Quality Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60 font-mono bg-white">
              {filteredObservations.length > 0 ? (
                filteredObservations.map((obs) => {
                  const latencyMin = getLatencyMinutes(obs.event_time, obs.arrival_time);
                  const isLate = latencyMin > LATENCY_THRESHOLD_MINUTES;
                  const kindCfg = SOURCE_KIND_CONFIG[obs.source_kind] || SOURCE_KIND_CONFIG.simulated;

                  return (
                    <tr
                      key={obs.obs_id}
                      className={`hover:bg-[#faf7ef] transition-colors ${
                        isLate ? 'border-l-4 border-l-risk-high bg-risk-high/[0.04]' : ''
                      }`}
                    >
                      {/* Node */}
                      <td className="py-3 px-4 font-bold text-text-primary">
                        <div className="flex items-center gap-2">
                          <span className="h-1.5 w-1.5 rounded-full bg-navy" />
                          <span>{obs.node_id || `${obs.zone}:${obs.system}`}</span>
                        </div>
                      </td>

                      {/* Source & Kind */}
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-1.5">
                          <span className="text-text-primary font-medium">{obs.source}</span>
                          <Tooltip content={kindCfg.description}>
                            <span
                              className={`text-[9px] px-1.5 py-0.2 rounded border font-semibold ${kindCfg.bgClass} ${kindCfg.textClass} ${kindCfg.borderClass}`}
                            >
                              {kindCfg.label}
                            </span>
                          </Tooltip>
                        </div>
                      </td>

                      {/* Value */}
                      <td className="py-3 px-3 font-bold text-navy tabular-nums text-sm">
                        {obs.value.toFixed(2)}
                      </td>

                      {/* Event Time */}
                      <td className="py-3 px-3 text-text-secondary tabular-nums">
                        <Tooltip content={`UTC: ${formatUtcTime(obs.event_time)}`}>
                          <span>{formatLocalTime(obs.event_time)}</span>
                        </Tooltip>
                      </td>

                      {/* Arrival Time */}
                      <td className="py-3 px-3 text-text-secondary tabular-nums">
                        <Tooltip content={`UTC: ${formatUtcTime(obs.arrival_time)}`}>
                          <span>{formatLocalTime(obs.arrival_time)}</span>
                        </Tooltip>
                      </td>

                      {/* Latency */}
                      <td className="py-3 px-3">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] tabular-nums font-semibold ${
                            isLate
                              ? 'bg-risk-high/20 text-text-primary border border-risk-high'
                              : 'text-text-muted'
                          }`}
                        >
                          {isLate && <Clock size={11} className="text-risk-high" />}
                          {formatDuration(latencyMin)}
                        </span>
                      </td>

                      {/* Quality Flags */}
                      <td className="py-3 px-4">
                        <div className="flex flex-wrap gap-1">
                          {obs.quality_flags && obs.quality_flags.length > 0 ? (
                            obs.quality_flags.map((flag, idx) => (
                              <span
                                key={idx}
                                className={`text-[10px] px-1.5 py-0.2 rounded border ${
                                  flag === 'dropout' || flag === 'spike' || flag === 'stuck_at'
                                    ? 'bg-risk-critical/15 text-risk-critical border-risk-critical/40'
                                    : flag === 'feed_delay'
                                    ? 'bg-risk-high/15 text-text-primary border-risk-high/40'
                                    : flag === 'real'
                                    ? 'bg-risk-normal/15 text-risk-normal border-risk-normal/40'
                                    : 'bg-surface-muted text-text-secondary border-border'
                                }`}
                              >
                                {flag}
                              </span>
                            ))
                          ) : (
                            <span className="text-text-muted text-[11px]">nominal</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-text-muted">
                    <Radio size={32} className="mx-auto text-text-muted/50 mb-2" />
                    <p className="text-sm font-semibold text-text-primary">No matching observations found</p>
                    <p className="text-xs text-text-muted mt-1">
                      {observations.length === 0
                        ? 'Waiting for incoming stream packets from WebSocket...'
                        : 'Try adjusting your filters or search term above.'}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};
