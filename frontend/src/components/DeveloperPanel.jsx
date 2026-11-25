import React from 'react'

const FAILURE_PRESETS = [
  { label: 'Off', value: '' },
  { label: 'key_1=429', value: 'key_1=429' },
  { label: 'key_1=500', value: 'key_1=500' },
  { label: 'key_1=429,key_2=500', value: 'key_1=429,key_2=500' },
  { label: '*=429', value: '*=429' },
]

export default function DeveloperPanel({
  open,
  onClose,
  simulateHeader,
  onSimulateHeaderChange,
  latestTelemetry,
  health,
  lastError,
}) {
  if (!open) return null

  const simulationUiEnabled = import.meta.env.VITE_ENABLE_FAILURE_SIMULATION === 'true'

  return (
    <aside className="dev-drawer" aria-label="Developer inspector">
      <div className="dev-drawer-header">
        <div>
          <div className="dev-drawer-title">Developer Inspector</div>
          <div className="dev-drawer-sub">Gateway telemetry & diagnostics</div>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Close developer panel"
        >
          ✕
        </button>
      </div>

      {simulationUiEnabled && (
        <div className="dev-card">
          <div className="dev-card-title">Failover Simulation Header</div>
          <p className="dev-hint">
            Injects <code>X-Simulate-Failure</code> on the next request when{' '}
            <code>ENABLE_FAILURE_SIMULATION=true</code>.
          </p>
          <div className="preset-grid">
            {FAILURE_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                className={`preset-chip ${simulateHeader === preset.value ? 'active' : ''}`}
                onClick={() => onSimulateHeaderChange(preset.value)}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <input
            type="text"
            className="sim-input"
            aria-label="Custom failure simulation header"
            placeholder="Custom e.g. key_1=502"
            value={simulateHeader}
            onChange={(e) => onSimulateHeaderChange(e.target.value)}
          />
        </div>
      )}

      <div className="dev-card">
        <div className="dev-card-title">Latest Request Telemetry</div>
        {latestTelemetry ? (
          <dl className="telemetry-grid">
            <dt>Resolution</dt>
            <dd>
              <span
                className={`tele-badge ${
                  latestTelemetry.resolution_source === 'LLM_CACHE' ? 'cache' : 'live'
                }`}
              >
                {latestTelemetry.resolution_source}
              </span>
            </dd>

            <dt>Selected Key ID</dt>
            <dd>
              <code>{latestTelemetry.key_id === null ? 'null' : latestTelemetry.key_id}</code>
            </dd>

            <dt>Fallback Attempts</dt>
            <dd className={latestTelemetry.fallback_attempts > 0 ? 'warn-text' : ''}>
              {latestTelemetry.fallback_attempts}
            </dd>

            <dt>Model</dt>
            <dd>
              <code>{latestTelemetry.model}</code>
            </dd>

            <dt>Latency</dt>
            <dd>{latestTelemetry.latency_ms} ms</dd>

            <dt>Input Tokens</dt>
            <dd>{latestTelemetry.input_tokens}</dd>

            <dt>Output Tokens</dt>
            <dd>{latestTelemetry.output_tokens}</dd>

            <dt>Cache Status</dt>
            <dd>{health.cache_enabled ? 'Enabled (LiteLLM)' : 'Disabled'}</dd>
          </dl>
        ) : (
          <div className="dev-empty">Send a message to inspect request telemetry.</div>
        )}
      </div>

      <div className="dev-card">
        <div className="dev-card-title">Last Backend Error</div>
        {lastError ? (
          <div className="dev-error-box">{lastError}</div>
        ) : (
          <div className="dev-empty">No errors recorded in this session.</div>
        )}
      </div>
    </aside>
  )
}
