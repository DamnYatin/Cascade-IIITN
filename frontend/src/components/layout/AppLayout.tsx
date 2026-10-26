import React, { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Header } from './Header';
import { Navigation } from './Navigation';
import { useStream } from '../../context/StreamContext';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from '../ui/Button';

export const AppLayout: React.FC = () => {
  const location = useLocation();
  const {
    cities,
    selectedCityId,
    setSelectedCityId,
    wsStatus,
    isBackendHealthy,
    checkHealth,
  } = useStream();

  useEffect(() => {
    const routeTitles: Record<string, string> = {
      '/': 'Overview | The 72-Hour Warning',
      '/operations': 'Live Operations | The 72-Hour Warning',
      '/cascade': 'Cascade Explorer | The 72-Hour Warning',
      '/forecasts': 'Forecasts | The 72-Hour Warning',
      '/replay': 'Event Replay | The 72-Hour Warning',
      '/sources': 'Data Sources | The 72-Hour Warning',
      '/diagnostics': 'System Diagnostics | The 72-Hour Warning',
    };
    document.title = routeTitles[location.pathname] || 'The 72-Hour Warning';

    const mainEl = document.getElementById('main-content');
    if (mainEl) {
      const heading = mainEl.querySelector('h1, h2, [role="heading"]');
      if (heading instanceof HTMLElement) {
        heading.setAttribute('tabindex', '-1');
        heading.focus({ preventScroll: true });
      } else {
        mainEl.setAttribute('tabindex', '-1');
        mainEl.focus({ preventScroll: true });
      }
    }
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [location.pathname]);

  return (
    <div className="min-h-screen bg-background text-text-primary flex flex-col antialiased selection:bg-accent-gold selection:text-navy-deep">
      {/* Skip Navigation — visible on keyboard focus, required for WCAG 2.1 AA */}
      <a href="#main-content" className="skip-nav">
        Skip to main content
      </a>

      {/* Backend Offline Warning Banner if unreachable */}
      {isBackendHealthy === false && (
        <div className="bg-risk-critical/15 border-b border-risk-critical/30 px-4 py-2 z-50 text-xs font-mono text-risk-critical flex items-center justify-between">
          <div className="flex items-center gap-2 max-w-7xl mx-auto flex-1">
            <AlertCircle size={15} className="shrink-0 text-risk-critical" />
            <span>
              <strong>FastAPI Backend Offline:</strong> Could not connect to http://127.0.0.1:8000/health. Ensure backend is running.
            </span>
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="text-xs h-7 text-risk-critical hover:text-text-primary"
            icon={<RefreshCw size={12} />}
            onClick={checkHealth}
          >
            Retry
          </Button>
        </div>
      )}

      {/* Persistent Header */}
      <Header
        cities={cities}
        selectedCityId={selectedCityId}
        onSelectCity={setSelectedCityId}
        wsStatus={wsStatus}
        isBackendHealthy={isBackendHealthy}
      />

      {/* Persistent Navigation */}
      <Navigation />

      {/* Main Page Content rendered via React Router Outlet */}
      <main id="main-content" className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-[#ece7d8]/60 py-5 text-xs text-text-muted font-mono">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>The 72-Hour Warning — Cascading Crisis Early Warning Platform</span>
          <span>Assam Hero Monsoon Scenario 2026 · Python/FastAPI Forecaster Backbone</span>
        </div>
      </footer>
    </div>
  );
};
