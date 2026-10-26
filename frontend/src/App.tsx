import React, { Suspense } from 'react';
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import { StreamProvider } from './context/StreamContext';
import { AppLayout } from './components/layout/AppLayout';
import { OverviewPage } from './components/overview/OverviewPage';
import { LiveOperationsPage } from './components/operations/LiveOperationsPage';
import { EventReplayPage } from './components/replay/EventReplayPage';
import { DataSourcesPage } from './components/sources/DataSourcesPage';
import { SystemDiagnosticsPage } from './components/diagnostics/SystemDiagnosticsPage';

// Code-split heavy routes with React.lazy per Section 6
const CascadeExplorerPage = React.lazy(() =>
  import('./components/cascade/CascadeExplorerPage').then((m) => ({ default: m.CascadeExplorerPage }))
);
const ForecastsPage = React.lazy(() =>
  import('./components/forecasts/ForecastsPage').then((m) => ({ default: m.ForecastsPage }))
);

const RouteSpinner = () => (
  <div className="flex items-center justify-center py-20 text-navy" role="status" aria-live="polite">
    <div className="flex flex-col items-center gap-3">
      <div className="h-7 w-7 rounded-full border-2 border-border border-t-navy animate-spin" />
      <span className="text-xs font-mono text-text-muted uppercase tracking-wider">
        Loading module...
      </span>
    </div>
  </div>
);

const NotFoundPage = () => (
  <div className="py-20 text-center space-y-4">
    <div className="h-12 w-12 rounded-xl bg-navy text-white mx-auto flex items-center justify-center font-mono font-bold text-lg">
      404
    </div>
    <h2 className="font-heading text-xl font-bold text-text-primary">
      Operational Route Not Found
    </h2>
    <p className="text-xs text-text-muted font-mono max-w-sm mx-auto">
      The specified operational section does not exist in the 72-Hour Warning platform.
    </p>
    <Link
      to="/"
      className="inline-flex items-center gap-2 px-4 py-2 bg-navy text-white text-xs font-mono font-semibold rounded-lg hover:bg-navy-deep transition-colors"
    >
      Return to Overview
    </Link>
  </div>
);

export function App() {
  return (
    <BrowserRouter>
      <StreamProvider>
        <Suspense fallback={<RouteSpinner />}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/operations" element={<LiveOperationsPage />} />
              <Route path="/cascade" element={<CascadeExplorerPage />} />
              <Route path="/forecasts" element={<ForecastsPage />} />
              <Route path="/replay" element={<EventReplayPage />} />
              <Route path="/sources" element={<DataSourcesPage />} />
              <Route path="/diagnostics" element={<SystemDiagnosticsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </Suspense>
      </StreamProvider>
    </BrowserRouter>
  );
}

export default App;
