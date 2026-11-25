export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')
).replace(/\/+$/, '')

export async function getHealth() {
  const res = await fetch(`${API_BASE_URL}/health`)
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    return {
      status: 'degraded',
      keys_configured: 0,
      cache_enabled: false,
      detail: data?.detail || `HTTP ${res.status}`,
    }
  }
  return data
}

export async function getSessionMessages(sessionId) {
  const res = await fetch(
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/messages`,
  )
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    throw new Error(data?.detail || `Failed to load history (HTTP ${res.status})`)
  }
  return data
}

export async function sendChatMessage({ sessionId, message, systemPrompt, simulateFailure }) {
  const headers = { 'Content-Type': 'application/json' }
  if (simulateFailure && simulateFailure.trim()) {
    headers['X-Simulate-Failure'] = simulateFailure.trim()
  }

  const body = { session_id: sessionId, message }
  if (systemPrompt && systemPrompt.trim()) {
    body.system_prompt = systemPrompt.trim()
  }

  const res = await fetch(`${API_BASE_URL}/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const detail =
      data && typeof data.detail === 'string'
        ? data.detail
        : Array.isArray(data?.detail)
          ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
          : `Request failed with HTTP ${res.status}`
    throw new Error(`HTTP ${res.status}: ${detail}`)
  }

  return data
}
