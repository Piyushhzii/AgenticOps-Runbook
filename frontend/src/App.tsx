import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Command,
  Database,
  GitBranch,
  Layers3,
  LayoutDashboard,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  MessageSquare,
  MoreHorizontal,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Terminal,
  TriangleAlert,
  Workflow,
  X,
} from 'lucide-react'
import {
  api,
  ApiError,
  title,
  type Readiness,
  type Runbook,
  type Session,
} from './api'

type View = 'overview' | 'runbooks' | 'sessions'
type Dialog = 'connection' | 'new' | 'resume' | 'escalate' | null
const prompts = [
  {
    label: 'Service degradation',
    text: 'Customers report that checkout is slow and some requests are failing.',
    icon: Activity,
  },
  {
    label: 'Login issue',
    text: 'A customer cannot sign in and sees an account error.',
    icon: LockKeyhole,
  },
  {
    label: 'Payment failure',
    text: 'A payment was deducted but the order is not confirmed.',
    icon: Layers3,
  },
]

export default function App() {
  const [view, setView] = useState<View>('overview')
  const [key, setKey] = useState('')
  const [keyDraft, setKeyDraft] = useState('')
  const [connected, setConnected] = useState(false)
  const [catalog, setCatalog] = useState<Runbook[]>([])
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [issue, setIssue] = useState('')
  const [reply, setReply] = useState('')
  const [resumeId, setResumeId] = useState('')
  const [search, setSearch] = useState('')
  const [needsReload, setNeedsReload] = useState(false)
  const session = sessions.find((item) => item.session_id === selectedId)
  const active = sessions.filter((item) => item.status === 'active').length
  const escalated = sessions.filter(
    (item) => item.status === 'escalated',
  ).length
  const complete = sessions.filter((item) => item.status === 'completed').length
  const transcript = useRef<HTMLDivElement>(null)
  const lastSessionId = useRef<string | null>(null)

  useEffect(() => {
    transcript.current?.scrollTo?.({
      top: transcript.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [session?.messages.length, busy])

  useEffect(() => {
    if (lastSessionId.current !== selectedId) {
      setReply('')
      setNeedsReload(false)
      lastSessionId.current = selectedId
    }
  }, [selectedId])

  function saveSession(next: Session) {
    setSessions((previous) => [
      next,
      ...previous.filter((item) => item.session_id !== next.session_id),
    ])
    setSelectedId(next.session_id)
    setView('sessions')
    setNeedsReload(false)
  }

  async function perform(action: () => Promise<void>, mutation = false) {
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Unexpected error. Please try again.',
      )
      if (mutation) setNeedsReload(true)
      if (caught instanceof ApiError && caught.status === 401) {
        setConnected(false)
        setDialog('connection')
      }
    } finally {
      setBusy(false)
    }
  }

  function openNew(text = '') {
    setIssue(text)
    setError('')
    setDialog(connected ? 'new' : 'connection')
  }

  function disconnect() {
    setKey('')
    setKeyDraft('')
    setConnected(false)
    setCatalog([])
    setReadiness(null)
    setSessions([])
    setSelectedId(null)
    setReply('')
    setIssue('')
    setResumeId('')
    setError('')
    setView('overview')
  }

  function start(event: FormEvent) {
    event.preventDefault()
    void perform(async () => {
      saveSession(await api.start(key, issue.trim()))
      setIssue('')
      setDialog(null)
    })
  }

  function connectWorkspace(event: FormEvent) {
    event.preventDefault()
    void perform(async () => {
      const nextKey = keyDraft.trim()
      const [items, health] = await Promise.all([
        api.catalog(nextKey),
        api.readiness(nextKey),
      ])
      if (nextKey !== key) {
        setSessions([])
        setSelectedId(null)
        setReply('')
        setIssue('')
        setResumeId('')
        setNeedsReload(false)
      }
      setKey(nextKey)
      setKeyDraft('')
      setCatalog(items)
      setReadiness(health)
      setConnected(true)
      setDialog(null)
    })
  }

  function send(event: FormEvent) {
    event.preventDefault()
    if (!session) return
    void perform(async () => {
      saveSession(await api.respond(key, session, reply.trim()))
      setReply('')
    }, true)
  }

  const filteredRunbooks = catalog.filter((item) =>
    `${item.runbook_id} ${item.description}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  )

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          aria-label="Runbook operations overview"
          href="#"
          onClick={(event) => {
            event.preventDefault()
            setView('overview')
          }}
        >
          <span className="brand-icon">
            <Workflow size={23} />
          </span>
          <span>
            runbook<span className="brand-period">.</span>
            <small>OPERATIONS COPILOT</small>
          </span>
        </a>
        <div className="workspace">
          <span className="workspace-avatar">OP</span>
          <div>
            Operations workspace<small>Internal environment</small>
          </div>
          <ChevronRight size={14} />
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="Main navigation">
          <button
            className={view === 'overview' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setView('overview')}
          >
            <LayoutDashboard size={18} />
            Overview
          </button>
          <button
            className={view === 'runbooks' ? 'nav-item selected' : 'nav-item'}
            onClick={() => {
              setView('runbooks')
              setSearch('')
            }}
          >
            <BookOpen size={18} />
            Runbook library<span className="nav-count">{catalog.length}</span>
          </button>
          <button
            className={view === 'sessions' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setView('sessions')}
          >
            <MessageSquare size={18} />
            Agent sessions<span className="nav-count">{sessions.length}</span>
          </button>
        </nav>
        <p className="nav-label second-label">CONTROL PLANE</p>
        <button
          className="nav-item"
          onClick={() => {
            setError('')
            setDialog('connection')
          }}
        >
          <GitBranch size={18} />
          API connection
          <span className={`tiny-dot ${connected ? 'green' : ''}`} />
        </button>
        <div className="sidebar-bottom">
          <div className="safety-card">
            <ShieldCheck size={19} />
            <strong>Human in the loop</strong>
            <p>
              You stay in control.
              <br />
              No external actions run automatically.
            </p>
            <span>
              SAFE EXECUTION MODE <LockKeyhole size={10} />
            </span>
          </div>
          <a
            className="help-link"
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
          >
            <CircleHelp size={17} />
            API documentation
            <ArrowUpRight size={14} />
          </a>
          <div className="operator">
            <span className="operator-avatar">OP</span>
            <div>
              Operations team<small>Operator workspace</small>
            </div>
            {connected && (
              <button
                className="icon-button"
                aria-label="Disconnect and clear workspace"
                disabled={busy}
                onClick={disconnect}
              >
                <LogOut size={16} />
              </button>
            )}
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace
            <ChevronRight size={13} />
            <strong>
              {view === 'overview'
                ? 'Overview'
                : view === 'runbooks'
                  ? 'Runbook library'
                  : 'Agent sessions'}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="environment-tag">
              <span className="tiny-dot green" />
              INTERNAL
            </span>
            <button
              className="connection-button"
              disabled={busy}
              onClick={() => {
                setError('')
                setDialog('connection')
              }}
            >
              <span className={`tiny-dot ${connected ? 'green' : 'amber'}`} />
              {connected ? 'API connected' : 'Connect API'}
            </button>
            <span className="top-avatar">OP</span>
          </div>
        </header>

        <main>
          {error && (
            <div className="error-banner" role="alert">
              <TriangleAlert size={18} />
              <div>
                <strong>Request needs attention</strong>
                <p>{error}</p>
                {needsReload && (
                  <small>
                    Reload the session before sending again. Your draft has been
                    preserved.
                  </small>
                )}
              </div>
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError('')}
              >
                <X size={16} />
              </button>
            </div>
          )}

          {view === 'overview' && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">
                    <span className="tiny-dot green" />
                    YOUR OPERATIONS, ORCHESTRATED
                  </div>
                  <h1>A calmer way to handle incidents.</h1>
                  <p>
                    Turn operational knowledge into guided, evidence-driven
                    action.
                  </p>
                </div>
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => openNew()}
                >
                  <Plus size={17} />
                  New session
                </button>
              </section>
              <section className="hero-panel">
                <div className="hero-copy">
                  <div className="hero-tag">
                    <Sparkles size={13} />
                    POWERED BY LANGGRAPH
                  </div>
                  <h2>
                    Less firefighting.
                    <br />
                    <span>More forward progress.</span>
                  </h2>
                  <p>
                    Describe what&apos;s happening. Your copilot finds the right
                    <br className="desktop-break" /> runbook and guides you
                    through the next best step.
                  </p>
                  <button
                    className="button light"
                    disabled={busy}
                    onClick={() => openNew()}
                  >
                    Start troubleshooting
                    <ArrowRight size={16} />
                  </button>
                  <div className="hero-footnote">
                    <ShieldCheck size={13} />
                    Evidence first. Operator always in control.
                  </div>
                </div>
                <div className="flow-art" aria-hidden="true">
                  <div className="art-grid" />
                  <div className="flow-orbit orbit-one" />
                  <div className="flow-orbit orbit-two" />
                  <div className="flow-node node-top">
                    <span>
                      <Activity size={18} />
                    </span>
                    <div>
                      Incident detected<small>Understand the context</small>
                    </div>
                    <span className="node-check">
                      <Check size={12} />
                    </span>
                  </div>
                  <div className="flow-line line-one" />
                  <div className="flow-node node-center">
                    <span className="purple-icon">
                      <Workflow size={21} />
                    </span>
                    <div>
                      Runbook intelligence<small>Reason. Route. Respond.</small>
                    </div>
                    <Sparkles size={15} />
                  </div>
                  <div className="flow-line line-two" />
                  <div className="flow-node node-bottom">
                    <span>
                      <ShieldCheck size={18} />
                    </span>
                    <div>
                      Operator checkpoint
                      <small>You approve the next step</small>
                    </div>
                    <span className="pulsing-dot" />
                  </div>
                  <span className="art-label">
                    A CLEAR PATH THROUGH THE COMPLEXITY
                  </span>
                </div>
              </section>

              <section className="stats-grid" aria-label="Workspace statistics">
                {[
                  {
                    label: 'Available runbooks',
                    value: catalog.length,
                    note: connected
                      ? 'From your live catalog'
                      : 'Connect to load catalog',
                    icon: BookOpen,
                    color: 'violet',
                  },
                  {
                    label: 'Active sessions',
                    value: active,
                    note: 'In this browser workspace',
                    icon: Activity,
                    color: 'blue',
                  },
                  {
                    label: 'Runbooks completed',
                    value: complete,
                    note: 'Completion is not verification',
                    icon: CheckCircle2,
                    color: 'green',
                  },
                  {
                    label: 'Needs handoff',
                    value: escalated,
                    note: 'Operator follow-up required',
                    icon: GitBranch,
                    color: 'orange',
                  },
                ].map((stat) => (
                  <article className="stat-card" key={stat.label}>
                    <div className="stat-top">
                      <span>{stat.label}</span>
                      <span className={`stat-icon ${stat.color}`}>
                        <stat.icon size={16} />
                      </span>
                    </div>
                    <strong>
                      {connected
                        ? stat.value.toString().padStart(2, '0')
                        : '--'}
                    </strong>
                    <small>{stat.note}</small>
                  </article>
                ))}
              </section>

              <div className="overview-lower">
                <section className="panel recent-panel">
                  <div className="panel-heading">
                    <div>
                      <h3>
                        Recent sessions{' '}
                        <span className="count-pill">{sessions.length}</span>
                      </h3>
                      <p>Your latest troubleshooting conversations.</p>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => setView('sessions')}
                    >
                      View all
                      <ArrowRight size={14} />
                    </button>
                  </div>
                  {sessions.length ? (
                    <SessionList
                      sessions={sessions.slice(0, 4)}
                      onSelect={(item) => {
                        setSelectedId(item.session_id)
                        setView('sessions')
                      }}
                    />
                  ) : (
                    <div className="empty-sessions">
                      <span className="empty-icon">
                        <MessageSquare size={23} />
                      </span>
                      <h4>A clear workspace. A fresh start.</h4>
                      <p>
                        Start a session to troubleshoot an issue,
                        <br />
                        or resume one using its session ID.
                      </p>
                      <button
                        className="button secondary small"
                        onClick={() => {
                          setError('')
                          setDialog(connected ? 'resume' : 'connection')
                        }}
                      >
                        Resume a session
                        <ArrowUpRight size={14} />
                      </button>
                    </div>
                  )}
                  <div className="panel-footer">
                    <LockKeyhole size={12} />
                    Session history is held in memory. Resume saved sessions by
                    ID.
                  </div>
                </section>
                <section className="panel quickstart-panel">
                  <div className="panel-heading">
                    <div>
                      <h3>Where should we start?</h3>
                      <p>A few common starting points.</p>
                    </div>
                    <Command size={17} />
                  </div>
                  <div className="quickstart-list">
                    {prompts.map((prompt) => (
                      <button
                        key={prompt.label}
                        onClick={() => openNew(prompt.text)}
                      >
                        <span className="quick-icon">
                          <prompt.icon size={18} />
                        </span>
                        <div>
                          <strong>{prompt.label}</strong>
                          <small>Describe, investigate, and triage</small>
                        </div>
                        <ArrowUpRight size={16} />
                      </button>
                    ))}
                  </div>
                  <div className="quick-note">
                    <Sparkles size={14} />
                    <p>
                      Examples are starting prompts. Your live catalog
                      determines which workflows are available.
                    </p>
                  </div>
                </section>
              </div>
              <footer className="page-footer">
                <span>
                  <Workflow size={13} />
                  Built for thoughtful operations.
                </span>
                <span>
                  LangGraph orchestration <span className="footer-dot">/</span>{' '}
                  Human-led decisions
                </span>
              </footer>
            </>
          )}

          {view === 'runbooks' && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">KNOWLEDGE INTO ACTION</div>
                  <h1>Your operational playbook.</h1>
                  <p>
                    Reviewed workflows. Clear routes. An operator at every
                    checkpoint.
                  </p>
                </div>
                <button
                  className="button secondary"
                  disabled={!connected || busy}
                  onClick={() =>
                    void perform(async () => {
                      setCatalog(await api.catalog(key))
                    })
                  }
                >
                  <RefreshCw size={15} />
                  Refresh catalog
                </button>
              </section>
              <div className="library-toolbar">
                <label className="search-field">
                  <Search size={17} />
                  <input
                    aria-label="Search runbooks"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search runbooks by name or description..."
                  />
                </label>
                <span>{filteredRunbooks.length} workflows available</span>
              </div>
              {!connected ? (
                <EmptyState
                  title="Connect your runbook catalog"
                  description="Connect to the API to browse real, ingested workflows."
                  action="Connect API"
                  onClick={() => setDialog('connection')}
                />
              ) : !filteredRunbooks.length ? (
                <EmptyState
                  title="No matching runbooks"
                  description="Try a different search, or ingest a reviewed JSON runbook on the backend."
                />
              ) : (
                <div className="runbook-grid">
                  {filteredRunbooks.map((runbook, index) => (
                    <article className="runbook-card" key={runbook.runbook_id}>
                      <div className="runbook-card-top">
                        <span className={`catalog-icon color-${index % 3}`}>
                          <BookOpen size={22} />
                        </span>
                        <span className="badge neutral">GUIDED WORKFLOW</span>
                      </div>
                      <h3>{title(runbook.runbook_id)}</h3>
                      <p>{runbook.description}</p>
                      <div className="runbook-card-bottom">
                        <span>
                          <ShieldCheck size={13} />
                          Operator-led
                        </span>
                        <button
                          className="text-button"
                          onClick={() =>
                            openNew(
                              `I need help with ${title(runbook.runbook_id).toLowerCase()}. `,
                            )
                          }
                        >
                          Start triage
                          <ArrowRight size={15} />
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              <div className="info-strip">
                <CircleHelp size={18} />
                <p>
                  Runbook selection is based on your issue description. Starting
                  triage does not force a particular workflow. Add new runbooks
                  through the backend ingestion command.
                </p>
              </div>
            </>
          )}

          {view === 'sessions' && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">EVIDENCE-DRIVEN TROUBLESHOOTING</div>
                  <h1>Agent workspace.</h1>
                  <p>
                    A conversation with context. A next step you can trust, then
                    verify.
                  </p>
                </div>
                <div className="button-row">
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() =>
                      setDialog(connected ? 'resume' : 'connection')
                    }
                  >
                    <RefreshCw size={15} />
                    Resume by ID
                  </button>
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => openNew()}
                  >
                    <Plus size={16} />
                    New session
                  </button>
                </div>
              </section>
              {sessions.length > 1 && (
                <label className="session-switcher">
                  <span>Current investigation</span>
                  <select
                    aria-label="Switch investigation"
                    value={selectedId ?? ''}
                    disabled={busy}
                    onChange={(event) => setSelectedId(event.target.value)}
                  >
                    {sessions.map((item) => (
                      <option key={item.session_id} value={item.session_id}>
                        {item.user_issue.slice(0, 80)} ({item.status})
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {!session ? (
                <>
                  <EmptyState
                    title="Your next investigation starts here"
                    description="Describe an issue in natural language, or resume a persisted session using its ID."
                    action="Start a session"
                    onClick={() => openNew()}
                  />
                  {sessions.length > 0 && (
                    <section className="panel">
                      <SessionList
                        sessions={sessions}
                        onSelect={(item) => setSelectedId(item.session_id)}
                      />
                    </section>
                  )}
                </>
              ) : (
                <div className="session-layout">
                  <section className="panel conversation-panel">
                    <div className="conversation-header">
                      <span className="agent-avatar">
                        <Workflow size={20} />
                      </span>
                      <div>
                        <h3>{title(session.runbook_id)}</h3>
                        <p>
                          Operations copilot{' '}
                          <span className="footer-dot">/</span> Version{' '}
                          {session.version}
                        </p>
                      </div>
                      <Status status={session.status} />
                      <button
                        className="icon-button"
                        aria-label="Reload session"
                        disabled={busy}
                        onClick={() =>
                          void perform(async () => {
                            saveSession(await api.load(key, session.session_id))
                          })
                        }
                      >
                        <RefreshCw size={16} />
                      </button>
                    </div>
                    <div
                      className="transcript"
                      ref={transcript}
                      role="log"
                      aria-label="Session conversation"
                      aria-live="polite"
                    >
                      <div className="conversation-notice">
                        <ShieldCheck size={13} />A guided conversation. No
                        external actions are executed.
                      </div>
                      {session.messages
                        .filter((message) => message.role !== 'system')
                        .map((message, index) => (
                          <div
                            key={`${message.created_at}-${index}`}
                            className={`message ${message.role === 'user' ? 'user-message' : 'agent-message'}`}
                          >
                            <span className="message-avatar">
                              {message.role === 'user' ? (
                                'OP'
                              ) : (
                                <Workflow size={15} />
                              )}
                            </span>
                            <div className="message-content">
                              <div className="message-meta">
                                <strong>
                                  {message.role === 'user'
                                    ? 'You'
                                    : 'Runbook copilot'}
                                </strong>
                                <time dateTime={message.created_at}>
                                  {new Date(
                                    message.created_at,
                                  ).toLocaleTimeString([], {
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  })}
                                </time>
                              </div>
                              <div className="message-bubble">
                                {message.message}
                              </div>
                            </div>
                          </div>
                        ))}
                      {busy && (
                        <div className="working-indicator" role="status">
                          <LoaderCircle size={16} className="spin" />
                          Processing your request...
                        </div>
                      )}
                    </div>
                    {session.status === 'active' ? (
                      <form className="composer" onSubmit={send}>
                        <label className="sr-only" htmlFor="reply">
                          Report evidence or answer the current question
                        </label>
                        <textarea
                          id="reply"
                          value={reply}
                          maxLength={8000}
                          disabled={busy || !connected}
                          onChange={(event) => setReply(event.target.value)}
                          placeholder={
                            session.awaiting_confirmation
                              ? 'Report the actual result of your authorized manual check...'
                              : 'Share what you know. Leave out passwords, tokens, and sensitive data.'
                          }
                        />
                        <div className="composer-bottom">
                          <span>
                            <LockKeyhole size={12} />
                            Operator-reported evidence only
                          </span>
                          <button
                            className="button primary small"
                            disabled={
                              busy || !connected || !reply.trim() || needsReload
                            }
                            type="submit"
                          >
                            {busy ? (
                              <LoaderCircle size={15} className="spin" />
                            ) : (
                              <Send size={15} />
                            )}
                            Send
                          </button>
                        </div>
                        {needsReload && (
                          <button
                            type="button"
                            className="text-button reload-link"
                            disabled={busy}
                            onClick={() =>
                              void perform(async () => {
                                saveSession(
                                  await api.load(key, session.session_id),
                                )
                              })
                            }
                          >
                            Reload session before continuing
                            <RefreshCw size={13} />
                          </button>
                        )}
                      </form>
                    ) : (
                      <div className={`closed-session ${session.status}`}>
                        <CheckCircle2 size={19} />
                        <div>
                          <strong>
                            {session.status === 'completed'
                              ? 'Runbook completed'
                              : 'Operator handoff required'}
                          </strong>
                          <p>
                            {session.status === 'completed'
                              ? 'Completion does not independently verify incident resolution.'
                              : 'Evidence is saved. No external ticket has been created.'}
                          </p>
                        </div>
                      </div>
                    )}
                  </section>
                  <aside className="session-details">
                    <section className="panel detail-panel">
                      <h3>
                        <Radio size={16} />
                        Session control
                      </h3>
                      <div className="detail-label">SESSION ID</div>
                      <code className="session-id">{session.session_id}</code>
                      <div className="checkpoint">
                        <span
                          className={`checkpoint-icon ${session.awaiting_confirmation ? 'orange' : 'violet'}`}
                        >
                          {session.awaiting_confirmation ? (
                            <ShieldCheck size={19} />
                          ) : (
                            <MessageSquare size={19} />
                          )}
                        </span>
                        <div>
                          <strong>
                            {session.status !== 'active'
                              ? 'Session closed'
                              : session.awaiting_confirmation
                                ? 'Operator checkpoint'
                                : 'Waiting for evidence'}
                          </strong>
                          <small>
                            {session.executed_steps.length} acknowledged steps
                          </small>
                        </div>
                      </div>
                      {session.current_step && (
                        <p className="step-instruction">
                          {session.current_step.instruction}
                        </p>
                      )}
                      {session.status === 'active' && (
                        <button
                          className="button danger-outline full-width"
                          disabled={busy || needsReload || !connected}
                          onClick={() => setDialog('escalate')}
                        >
                          <ArrowUpRight size={15} />
                          Escalate to an operator
                        </button>
                      )}
                    </section>
                    <section className="panel detail-panel">
                      <h3>
                        <Database size={16} />
                        Collected evidence
                      </h3>
                      {Object.keys(session.context).length ? (
                        <div className="evidence-list">
                          {Object.entries(session.context).map(
                            ([id, value], index) => (
                              <div key={id}>
                                <span>OBSERVATION {index + 1}</span>
                                <p>
                                  {typeof value === 'string'
                                    ? value
                                    : JSON.stringify(value)}
                                </p>
                              </div>
                            ),
                          )}
                        </div>
                      ) : (
                        <p className="muted small-copy">
                          Evidence will appear here as you answer each step. No
                          system findings are inferred.
                        </p>
                      )}
                    </section>
                    <section className="panel detail-panel">
                      <h3>
                        <GitBranch size={16} />
                        Last turn trace
                      </h3>
                      {session.trace.length ? (
                        <ol className="trace-list">
                          {session.trace.map((node, index) => (
                            <li key={`${node}-${index}`}>
                              <span />
                              <span>{title(node)}</span>
                              <Check size={12} />
                            </li>
                          ))}
                        </ol>
                      ) : (
                        <p className="muted small-copy">
                          Saved session loaded. A new trace appears after the
                          next turn.
                        </p>
                      )}
                      <p className="trace-note">
                        Execution path, not model reasoning.
                      </p>
                    </section>
                  </aside>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {dialog && (
        <Modal
          title={
            dialog === 'connection'
              ? 'Connect your workspace'
              : dialog === 'new'
                ? 'Start an investigation'
                : dialog === 'resume'
                  ? 'Pick up where you left off'
                  : 'Request operator handoff'
          }
          onClose={() => {
            if (!busy) {
              setDialog(null)
              setError('')
            }
          }}
          busy={busy}
        >
          {error && (
            <div className="modal-error" role="alert">
              {error}
            </div>
          )}
          {dialog === 'connection' && (
            <form onSubmit={connectWorkspace}>
              <p className="modal-description">
                Use the application&apos;s <code>OPS_API_KEY</code>, not your
                Groq key. Credentials stay in memory and are cleared on refresh
                or disconnect.
              </p>
              <label className="field-label" htmlFor="api-key">
                Application API key
              </label>
              <input
                id="api-key"
                className="text-input"
                type="password"
                autoComplete="off"
                value={keyDraft}
                onChange={(event) => setKeyDraft(event.target.value)}
                placeholder="Paste your OPS_API_KEY"
                disabled={busy}
              />
              <p className="field-help">
                Local development without authentication? Leave this empty.
              </p>
              <div className="endpoint-preview">
                <Terminal size={15} />
                <span>
                  Same-origin proxy <code>/api</code>
                </span>
                <LockKeyhole size={13} />
              </div>
              {readiness?.status === 'not_ready' && (
                <p className="modal-warning">
                  The API is reachable but not ready. Check runbook ingestion
                  and provider configuration.
                </p>
              )}
              <div className="modal-actions">
                {connected && (
                  <button
                    type="button"
                    className="button secondary"
                    disabled={busy}
                    onClick={() => {
                      disconnect()
                      setDialog(null)
                    }}
                  >
                    Disconnect
                  </button>
                )}
                <button
                  className="button primary"
                  disabled={busy}
                  type="submit"
                >
                  {busy ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <LockKeyhole size={15} />
                  )}
                  Connect securely
                </button>
              </div>
            </form>
          )}
          {dialog === 'new' && (
            <form onSubmit={start}>
              <p className="modal-description">
                Tell the copilot what&apos;s happening in your own words. It
                will select an available runbook and guide the investigation.
              </p>
              <label className="field-label" htmlFor="issue">
                What needs your attention?
              </label>
              <textarea
                id="issue"
                className="issue-input"
                value={issue}
                maxLength={8000}
                onChange={(event) => setIssue(event.target.value)}
                placeholder="For example: Checkout is slow in production and some orders are failing..."
                disabled={busy}
              />
              <div className="input-footnote">
                <span>Do not include secrets or sensitive customer data.</span>
                <span>{issue.length}/8000</span>
              </div>
              <div className="modal-actions">
                <button
                  className="button primary"
                  disabled={busy || issue.trim().length < 3 || !connected}
                  type="submit"
                >
                  {busy ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <Sparkles size={16} />
                  )}
                  Begin investigation
                  <ArrowRight size={15} />
                </button>
              </div>
            </form>
          )}
          {dialog === 'resume' && (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void perform(async () => {
                  saveSession(await api.load(key, resumeId.trim()))
                  setResumeId('')
                  setDialog(null)
                })
              }}
            >
              <p className="modal-description">
                Sessions are persisted by the backend. Paste a session ID from a
                previous investigation to restore its conversation and evidence.
              </p>
              <label className="field-label" htmlFor="resume-id">
                Session ID
              </label>
              <input
                id="resume-id"
                className="text-input"
                value={resumeId}
                onChange={(event) => setResumeId(event.target.value)}
                maxLength={100}
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                disabled={busy}
              />
              <div className="modal-actions">
                <button
                  className="button primary"
                  disabled={busy || !resumeId.trim()}
                >
                  {busy ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <ArrowRight size={16} />
                  )}
                  Resume session
                </button>
              </div>
            </form>
          )}
          {dialog === 'escalate' && (
            <>
              <p className="modal-description">
                This closes the current session as escalated and preserves its
                evidence. You must arrange the actual handoff separately; no
                external ticket is created.
              </p>
              {needsReload && (
                <p className="modal-warning">
                  Close this dialog and reload the session before trying again.
                </p>
              )}
              <div className="modal-actions">
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => setDialog(null)}
                >
                  Keep investigating
                </button>
                <button
                  className="button primary"
                  disabled={busy || needsReload}
                  onClick={() => {
                    if (session)
                      void perform(async () => {
                        saveSession(
                          await api.respond(key, session, '/escalate'),
                        )
                        setDialog(null)
                      }, true)
                  }}
                >
                  {busy ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <ArrowUpRight size={16} />
                  )}
                  Confirm escalation
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
      {connected && readiness?.status !== 'ready' && (
        <div className="readiness-toast" role="status">
          <TriangleAlert size={16} />
          API connected; configuration is not ready.
          <button
            aria-label="Review connection"
            onClick={() => setDialog('connection')}
          >
            <MoreHorizontal size={17} />
          </button>
        </div>
      )}
    </div>
  )
}

function Status({ status }: { status: Session['status'] }) {
  return (
    <span className={`badge ${status}`}>
      <span className="tiny-dot" />
      {status === 'active'
        ? 'In progress'
        : status === 'completed'
          ? 'Completed'
          : 'Needs handoff'}
    </span>
  )
}

function SessionList({
  sessions,
  onSelect,
}: {
  sessions: Session[]
  onSelect: (session: Session) => void
}) {
  return (
    <div className="session-list">
      {sessions.map((session) => (
        <button key={session.session_id} onClick={() => onSelect(session)}>
          <span className="session-list-icon">
            <MessageSquare size={17} />
          </span>
          <div>
            <strong>{session.user_issue}</strong>
            <small>
              {title(session.runbook_id)} <span className="footer-dot">/</span>{' '}
              v{session.version}
            </small>
          </div>
          <Status status={session.status} />
          <ChevronRight size={15} />
        </button>
      ))}
    </div>
  )
}

function EmptyState({
  title: heading,
  description,
  action,
  onClick,
}: {
  title: string
  description: string
  action?: string
  onClick?: () => void
}) {
  return (
    <div className="panel full-empty">
      <span className="empty-icon">
        <Workflow size={28} />
      </span>
      <h3>{heading}</h3>
      <p>{description}</p>
      {action && (
        <button className="button primary" onClick={onClick}>
          {action}
          <ArrowRight size={16} />
        </button>
      )}
    </div>
  )
}

function Modal({
  title: heading,
  onClose,
  busy,
  children,
}: {
  title: string
  onClose: () => void
  busy: boolean
  children: React.ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    dialog?.showModal()
    return () => {
      dialog?.close()
    }
  }, [])
  return (
    <dialog
      ref={ref}
      className="modal"
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onClose()
      }}
      aria-labelledby="modal-heading"
    >
      <div className="modal-header">
        <span className="modal-icon">
          <Workflow size={22} />
        </span>
        <button
          className="icon-button"
          aria-label="Close dialog"
          disabled={busy}
          onClick={onClose}
        >
          <X size={19} />
        </button>
      </div>
      <h2 id="modal-heading">{heading}</h2>
      {children}
    </dialog>
  )
}
