import React, { useState } from 'react'

export default function Sidebar({
  isOpen,
  isMobileOpen,
  onCloseMobile,
  onCollapseDesktop,
  onNewChat,
  isLoading,
  sessions,
  activeSessionId,
  onSelectSession,
  systemPrompt,
  onSystemPromptChange,
  theme,
  onToggleTheme,
  health,
}) {
  const [settingsOpen, setSettingsOpen] = useState(true)

  return (
    <>
      {isMobileOpen && (
        <div
          className="sidebar-backdrop"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      )}

      <aside className={`sidebar ${isOpen ? '' : 'collapsed'} ${isMobileOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-top">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <div>
              <div className="brand-title">Lyftr AI</div>
              <div className="brand-subtitle">Resilient Gateway</div>
            </div>
          </div>

          <button
            type="button"
            className="icon-btn desktop-only"
            onClick={onCollapseDesktop}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
          >
            «
          </button>
          <button
            type="button"
            className="icon-btn mobile-only"
            onClick={onCloseMobile}
            title="Close sidebar"
            aria-label="Close sidebar"
          >
            ✕
          </button>
        </div>

        <button
          type="button"
          className="new-chat-btn"
          onClick={onNewChat}
          disabled={isLoading}
        >
          <span className="plus-icon">+</span>
          <span>New chat</span>
        </button>

        <div className="sidebar-conversations">
          <div className="section-label">Conversations</div>
          <div className="session-list" role="list">
            {sessions.map((sess) => {
              const isActive = sess.id === activeSessionId
              return (
                <div key={sess.id} role="listitem">
                  <button
                    type="button"
                    className={`session-item ${isActive ? 'active' : ''}`}
                    onClick={() => onSelectSession(sess.id)}
                    disabled={isLoading && !isActive}
                    title={`Session ${sess.id}`}
                  >
                    <div className="session-item-title">{sess.title || 'New conversation'}</div>
                    <div className="session-item-meta">
                      <code>{sess.id}</code>
                      {sess.messageCount > 0 && <span>{sess.messageCount} msgs</span>}
                    </div>
                  </button>
                </div>
              )
            })}
          </div>
        </div>

        <div className="sidebar-settings">
          <button
            type="button"
            className="settings-toggle"
            onClick={() => setSettingsOpen((v) => !v)}
            aria-expanded={settingsOpen}
          >
            <span>Settings</span>
            <span className="chevron">{settingsOpen ? '▾' : '▸'}</span>
          </button>

          {settingsOpen && (
            <div className="settings-body">
              <div className="setting-group">
                <label htmlFor="system-prompt-input" className="setting-label">
                  System prompt
                </label>
                <textarea
                  id="system-prompt-input"
                  data-testid="system-prompt-input"
                  className="system-prompt-box"
                  rows={3}
                  placeholder="Optional instructions for this session..."
                  value={systemPrompt}
                  onChange={(e) => onSystemPromptChange(e.target.value)}
                />
              </div>

              <div className="setting-row">
                <span className="setting-label">Theme</span>
                <button
                  type="button"
                  className="theme-pill-btn"
                  onClick={onToggleTheme}
                  aria-label={`${theme === 'dark' ? 'Dark' : 'Light'} theme, click to toggle`}
                >
                  {theme === 'dark' ? 'Dark' : 'Light'}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="sidebar-footer">
          <div
            className={`health-pill ${health.status}`}
            title={
              health.status === 'ok'
                ? `${health.keys_configured} provider keys configured, cache ${health.cache_enabled ? 'enabled' : 'disabled'}`
                : health.detail || 'Backend status'
            }
          >
            <span className="health-dot" />
            <span className="health-text">
              {health.status === 'ok'
                ? `Online • ${health.keys_configured} keys`
                : health.status === 'checking'
                  ? 'Connecting...'
                  : health.status === 'degraded'
                    ? `Backend up • ${health.detail || 'Not ready'}`
                    : 'Gateway offline'}
            </span>
          </div>
        </div>
      </aside>
    </>
  )
}
