import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function formatTime(isoString) {
  try {
    return new Date(isoString).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

function CodeBlock({ inline, className, children, ...props }) {
  const [copied, setCopied] = useState(false)
  const match = /language-(\w+)/.exec(className || '')
  const codeText = String(children).replace(/\n$/, '')

  if (inline || (!match && !codeText.includes('\n'))) {
    return (
      <code className="inline-code" {...props}>
        {children}
      </code>
    )
  }

  async function handleCopyCode() {
    try {
      await navigator.clipboard.writeText(codeText)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {}
  }

  return (
    <div className="code-block-wrap">
      <div className="code-block-header">
        <span className="code-lang">{match ? match[1] : 'code'}</span>
        <button type="button" className="copy-mini-btn" onClick={handleCopyCode}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="code-pre">
        <code className={className} {...props}>
          {codeText}
        </code>
      </pre>
    </div>
  )
}

export default function MessageItem({ msg }) {
  const [copied, setCopied] = useState(false)

  if (msg.role === 'user') {
    return (
      <div className="message-row user-row">
        <div className="user-bubble">
          <div className="user-text">{msg.content}</div>
          <div className="msg-timestamp">{formatTime(msg.timestamp)}</div>
        </div>
      </div>
    )
  }

  async function handleCopyReply() {
    try {
      await navigator.clipboard.writeText(msg.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {}
  }

  return (
    <article className="message-row assistant-row" data-testid="assistant-message">
      <div className="assistant-avatar" aria-hidden="true">
        L
      </div>

      <div className="assistant-body">
        <div className="assistant-head">
          <div className="assistant-head-left">
            <span className="assistant-name">Lyftr AI</span>
            <span className="msg-timestamp">{formatTime(msg.timestamp)}</span>
          </div>
          <button
            type="button"
            className="copy-reply-btn"
            onClick={handleCopyReply}
            title="Copy response markdown"
          >
            {copied ? 'Copied ✓' : 'Copy'}
          </button>
        </div>

        <div className="markdown-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              pre: ({ children }) => <>{children}</>,
              code: CodeBlock,
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer">
                  {children}
                </a>
              ),
            }}
          >
            {msg.content}
          </ReactMarkdown>
        </div>

        {msg.metadata && (
          <div className="metadata-strip">
            <span
              data-testid="meta-source"
              title="Whether response came from LiteLLM cache (LLM_CACHE) or live provider call (LIVE_INFERENCE)"
              className={`meta-pill source ${
                msg.metadata.resolution_source === 'LLM_CACHE' ? 'cache' : 'live'
              }`}
            >
              <span className="source-dot" />
              {msg.metadata.resolution_source}
            </span>

            <span className="meta-pill" title="LiteLLM model identifier">
              <span className="meta-lbl">Model</span>
              <span data-testid="meta-model" className="meta-val">
                {msg.metadata.model}
              </span>
            </span>

            <span className="meta-pill" title="Server-measured request latency in milliseconds">
              <span className="meta-lbl">Latency</span>
              <span data-testid="meta-latency" className="meta-val">
                {msg.metadata.latency_ms} ms
              </span>
            </span>

            <span className="meta-pill" title="Prompt tokens for this request (system + history + message)">
              <span className="meta-lbl">In</span>
              <span data-testid="meta-input-tokens" className="meta-val">
                {msg.metadata.input_tokens}
              </span>
            </span>

            <span className="meta-pill" title="Completion tokens generated for this reply">
              <span className="meta-lbl">Out</span>
              <span data-testid="meta-output-tokens" className="meta-val">
                {msg.metadata.output_tokens}
              </span>
            </span>
          </div>
        )}
      </div>
    </article>
  )
}
