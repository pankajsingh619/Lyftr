import React, { useEffect, useRef, useState } from 'react'
import { getHealth, getSessionMessages, sendChatMessage } from './api/chatApi'
import DeveloperPanel from './components/DeveloperPanel'
import MessageItem from './components/MessageItem'
import Sidebar from './components/Sidebar'

const SESSIONS_STORAGE_KEY = 'lyftr_sessions_v1'

function generateSessionId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `s-${crypto.randomUUID().slice(0, 8)}`
  }
  return `s-${Math.random().toString(36).slice(2, 10)}`
}

function loadSavedSessions() {
  try {
    const raw = localStorage.getItem(SESSIONS_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

const SUGGESTED_PROMPTS = [
  {
    title: 'Test live inference & tokens',
    prompt: 'What is the capital of France? Answer in one short sentence.',
  },
  {
    title: 'Explain resilient AI routing',
    prompt: 'Explain how API key failover and response caching improve an LLM gateway, with a brief Python pseudocode snippet.',
  },
  {
    title: 'Verify formatted Markdown',
    prompt: 'Compare REST vs WebSockets for AI chat in a concise 3-row Markdown table.',
  },
]

export default function App() {
  const [theme, setTheme] = useState('dark')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [devPanelOpen, setDevPanelOpen] = useState(false)

  const [initialBoot] = useState(() => {
    const initialId = generateSessionId()
    const saved = loadSavedSessions()
    return { initialId, saved }
  })

  const [activeSessionId, setActiveSessionId] = useState(initialBoot.initialId)
  const [sessionList, setSessionList] = useState(() => [
    { id: initialBoot.initialId, title: 'New conversation', messageCount: 0, updatedAt: Date.now() },
    ...initialBoot.saved.filter((s) => s.id !== initialBoot.initialId).slice(0, 24),
  ])

  const [systemPrompt, setSystemPrompt] = useState('')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [errorState, setErrorState] = useState(null) // { message, retryText }
  const [health, setHealth] = useState({ status: 'checking', keys_configured: 0, cache_enabled: false })
  const [simulateHeader, setSimulateHeader] = useState('')
  const [latestTelemetry, setLatestTelemetry] = useState(null)
  const [showScrollBottom, setShowScrollBottom] = useState(false)

  const chatScrollRef = useRef(null)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const inFlightRef = useRef(false)
  const simulationUiEnabled = import.meta.env.VITE_ENABLE_FAILURE_SIMULATION === 'true'

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    try {
      const toStore = sessionList.filter((s) => s.messageCount > 0).slice(0, 25)
      localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(toStore))
    } catch {}
  }, [sessionList])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, errorState])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [input])

  async function refreshHealth() {
    try {
      setHealth(await getHealth())
    } catch {
      setHealth({ status: 'offline', keys_configured: 0, cache_enabled: false })
    }
  }

  useEffect(() => {
    refreshHealth()
    const timer = setInterval(refreshHealth, 30000)
    return () => clearInterval(timer)
  }, [])

  function upsertSessionMeta(targetId, userText, newCount) {
    setSessionList((prev) => {
      const existing = prev.find((s) => s.id === targetId)
      const nextTitle =
        existing && existing.title && existing.title !== 'New conversation'
          ? existing.title
          : userText.slice(0, 42) + (userText.length > 42 ? '…' : '')
      const updated = {
        id: targetId,
        title: nextTitle,
        messageCount: newCount,
        updatedAt: Date.now(),
      }
      return [updated, ...prev.filter((s) => s.id !== targetId)]
    })
  }

  function handleNewChat() {
    if (isLoading || inFlightRef.current) return
    const nextId = generateSessionId()
    setActiveSessionId(nextId)
    setMessages([])
    setErrorState(null)
    setLatestTelemetry(null)
    setSessionList((prev) => [
      { id: nextId, title: 'New conversation', messageCount: 0, updatedAt: Date.now() },
      ...prev,
    ])
    setMobileSidebarOpen(false)
  }

  async function loadSessionFromBackend(targetId, showNotFoundError = false) {
    setErrorState(null)
    try {
      const data = await getSessionMessages(targetId)
      const loaded = (data.messages || []).map((m, idx) => ({
        id: `loaded-${targetId}-${idx}`,
        role: m.role,
        content: m.content,
        metadata: m.metadata || null,
        timestamp: new Date().toISOString(),
      }))
      setMessages(loaded)
      const lastAssistant = [...loaded].reverse().find((m) => m.role === 'assistant' && m.metadata)
      setLatestTelemetry(lastAssistant ? lastAssistant.metadata : null)
      const firstUser = loaded.find((m) => m.role === 'user')
      if (firstUser) {
        upsertSessionMeta(targetId, firstUser.content, loaded.length)
      }
    } catch (err) {
      if (showNotFoundError) {
        setErrorState({ message: err.message || 'Could not load session history.', retryText: null })
      } else {
        setMessages([])
        setLatestTelemetry(null)
      }
    }
  }

  async function handleSelectSession(targetId) {
    if (isLoading || inFlightRef.current) return
    setActiveSessionId(targetId)
    setMobileSidebarOpen(false)
    await loadSessionFromBackend(targetId, false)
  }

  async function sendMessage(overrideText) {
    const rawText = typeof overrideText === 'string' ? overrideText : input
    if (isLoading || inFlightRef.current) return

    const trimmed = rawText.trim()
    if (!trimmed) {
      setErrorState({ message: 'Please enter a message before sending.', retryText: null })
      return
    }

    inFlightRef.current = true
    setErrorState(null)
    setIsLoading(true)
    const userTimestamp = new Date().toISOString()

    try {
      const data = await sendChatMessage({
        sessionId: activeSessionId,
        message: rawText,
        systemPrompt,
        simulateFailure: simulationUiEnabled ? simulateHeader : '',
      })

      setInput('')
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto'
      }

      setMessages((prev) => {
        const next = [
          ...prev,
          {
            id: `user-${Date.now()}`,
            role: 'user',
            content: trimmed,
            timestamp: userTimestamp,
          },
          {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: data.reply,
            metadata: data.metadata,
            timestamp: new Date().toISOString(),
          },
        ]
        upsertSessionMeta(activeSessionId, trimmed, next.length)
        return next
      })
      setLatestTelemetry(data.metadata)
    } catch (err) {
      setErrorState({
        message: err.message || 'Network error: Could not connect to the backend gateway.',
        retryText: rawText,
      })
    } finally {
      inFlightRef.current = false
      setIsLoading(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  function handleChatScroll() {
    const el = chatScrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setShowScrollBottom(distanceFromBottom > 120)
  }

  function scrollToBottom() {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const activeSession = sessionList.find((s) => s.id === activeSessionId)

  return (
    <div className="app-shell">
      <Sidebar
        isOpen={sidebarOpen}
        isMobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
        onCollapseDesktop={() => setSidebarOpen(false)}
        onNewChat={handleNewChat}
        isLoading={isLoading}
        sessions={sessionList}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        systemPrompt={systemPrompt}
        onSystemPromptChange={setSystemPrompt}
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
        health={health}
      />

      <main className="chat-main">
        <header className="chat-header">
          <div className="header-left">
            {!sidebarOpen && (
              <button
                type="button"
                className="icon-btn desktop-only"
                onClick={() => setSidebarOpen(true)}
                title="Expand sidebar"
                aria-label="Expand sidebar"
              >
                ☰
              </button>
            )}
            <button
              type="button"
              className="icon-btn mobile-only"
              onClick={() => setMobileSidebarOpen(true)}
              title="Open menu"
              aria-label="Open menu"
            >
              ☰
            </button>

            <div className="header-title-group">
              <h1 className="header-title">
                {activeSession?.title || 'New conversation'}
              </h1>
              <span className="session-pill" title="Active SQLite session ID">
                <code>{activeSessionId}</code>
              </span>
            </div>
          </div>

          <div className="header-actions">
            {simulationUiEnabled && simulateHeader.trim() && (
              <span className="sim-active-badge" title="Active X-Simulate-Failure header">
                Sim: {simulateHeader.trim()}
              </span>
            )}
            <button
              type="button"
              className="header-btn"
              onClick={() => loadSessionFromBackend(activeSessionId, true)}
              disabled={isLoading}
              title="Reload messages from SQLite"
            >
              Sync
            </button>
            <button
              type="button"
              className={`header-btn ${devPanelOpen ? 'active' : ''}`}
              onClick={() => setDevPanelOpen((v) => !v)}
              aria-expanded={devPanelOpen}
            >
              Developer
            </button>
          </div>
        </header>

        <div className="chat-workspace">
          <div className="chat-scroll" ref={chatScrollRef} onScroll={handleChatScroll}>
            {messages.length === 0 ? (
              <div className="welcome-wrap">
                <div className="welcome-hero">
                  <div className="welcome-eyebrow">LiteLLM Gateway • Key Failover • Response Cache</div>
                  <h2>What can I help you explore today?</h2>
                  <p>
                    Conversations persist in SQLite per session. Every assistant reply includes
                    resolution source, model, latency, and per-request token counts.
                  </p>
                </div>

                <div className="suggested-grid">
                  {SUGGESTED_PROMPTS.map((item) => (
                    <button
                      key={item.title}
                      type="button"
                      className="suggested-card"
                      onClick={() => sendMessage(item.prompt)}
                      disabled={isLoading}
                    >
                      <div className="suggested-title">{item.title}</div>
                      <div className="suggested-text">{item.prompt}</div>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="messages-column" aria-live="polite">
                {messages.map((msg) => (
                  <MessageItem key={msg.id} msg={msg} />
                ))}

                {isLoading && (
                  <div className="message-row assistant-row">
                    <div className="assistant-avatar" aria-hidden="true">
                      L
                    </div>
                    <div className="assistant-body loading-body">
                      <span className="typing-dots" aria-hidden="true">
                        <span />
                        <span />
                        <span />
                      </span>
                      <span className="loading-text">Generating response…</span>
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            )}

            {errorState && (
              <div className="error-banner" role="alert">
                <div className="error-msg">
                  <strong>Request failed:</strong> {errorState.message}
                </div>
                <div className="error-actions">
                  {errorState.retryText && (
                    <button
                      type="button"
                      className="retry-btn"
                      onClick={() => sendMessage(errorState.retryText)}
                      disabled={isLoading}
                    >
                      Retry
                    </button>
                  )}
                  <button
                    type="button"
                    className="error-close"
                    onClick={() => setErrorState(null)}
                    aria-label="Dismiss error"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )}
          </div>

          {showScrollBottom && (
            <button
              type="button"
              className="scroll-bottom-btn"
              onClick={scrollToBottom}
              aria-label="Scroll to latest message"
            >
              ↓ Scroll to bottom
            </button>
          )}

          <footer className="composer-wrap">
            <div className="composer-card">
              <textarea
                ref={textareaRef}
                data-testid="chat-input"
                className="chat-input"
                rows={1}
                placeholder="Message Lyftr AI… (Enter to send, Shift+Enter for new line)"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
              />
              <button
                type="button"
                data-testid="send-button"
                className="send-button"
                onClick={() => sendMessage()}
                disabled={isLoading}
                aria-label="Send message"
                title="Send message"
              >
                {isLoading ? (
                  <span className="btn-spinner" aria-hidden="true" />
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                )}
              </button>
            </div>
            <div className="composer-footnote">
              Session <code>{activeSessionId}</code> • Shift+Enter for newline
            </div>
          </footer>
        </div>
      </main>

      <DeveloperPanel
        open={devPanelOpen}
        onClose={() => setDevPanelOpen(false)}
        simulateHeader={simulateHeader}
        onSimulateHeaderChange={setSimulateHeader}
        latestTelemetry={latestTelemetry}
        health={health}
        lastError={errorState?.message || null}
      />
    </div>
  )
}
