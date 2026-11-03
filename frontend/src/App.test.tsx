import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { api, ApiError, type Session } from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    api: {
      catalog: vi.fn(),
      readiness: vi.fn(),
      start: vi.fn(),
      load: vi.fn(),
      respond: vi.fn(),
    },
  }
})

const initial: Session = {
  session_id: 'session-one',
  user_issue: 'Checkout is slow',
  runbook_id: 'SERVICE_TRIAGE',
  status: 'active',
  version: 1,
  awaiting_user_input: true,
  awaiting_confirmation: false,
  current_step: {
    step_id: 'scope',
    step_order: 1,
    instruction: 'Which environment?',
    step_type: 'input',
  },
  executed_steps: [],
  context: {},
  messages: [
    {
      role: 'user',
      message: 'Checkout is slow',
      created_at: '2026-10-27T06:00:00Z',
    },
    {
      role: 'assistant',
      message: 'Which environment is affected?',
      created_at: '2026-10-27T06:00:01Z',
    },
  ],
  trace: ['select_runbook', 'respond'],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.catalog).mockResolvedValue([
    { runbook_id: 'SERVICE_TRIAGE', description: 'Inspect service health.' },
  ])
  vi.mocked(api.readiness).mockResolvedValue({
    status: 'ready',
    checks: { database: true },
  })
  vi.mocked(api.start).mockResolvedValue(structuredClone(initial))
})

async function connect() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Connect API' }))
  const dialog = screen.getByRole('dialog')
  await user.type(
    within(dialog).getByLabelText('Application API key'),
    'test-key',
  )
  await user.click(
    within(dialog).getByRole('button', { name: 'Connect securely' }),
  )
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  )
  return user
}

async function startSession() {
  const user = await connect()
  await user.click(screen.getByRole('button', { name: 'New session' }))
  await user.type(
    screen.getByLabelText('What needs your attention?'),
    'Checkout is slow',
  )
  await user.click(screen.getByRole('button', { name: 'Begin investigation' }))
  await screen.findByText('Which environment is affected?')
  return user
}

describe('Operations console', () => {
  it('shows an honest disconnected dashboard and does not persist credentials', async () => {
    const storageSpy = vi.spyOn(window.Storage.prototype, 'setItem')
    render(<App />)
    expect(
      screen.getByText('A calmer way to handle incidents.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Connect to load catalog')).toBeInTheDocument()
    await connect()
    expect(api.catalog).toHaveBeenCalledWith('test-key')
    expect(storageSpy).not.toHaveBeenCalled()
    expect(screen.getByText('API connected')).toBeInTheDocument()
  })

  it('loads and searches the actual catalog', async () => {
    render(<App />)
    const user = await connect()
    await user.click(screen.getByRole('button', { name: /Runbook library/ }))
    expect(screen.getByText('Service Triage')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Search runbooks'), 'not-present')
    expect(screen.getByText('No matching runbooks')).toBeInTheDocument()
  })

  it('starts a natural language session and submits with the current version', async () => {
    vi.mocked(api.respond).mockResolvedValue({
      ...initial,
      version: 2,
      awaiting_confirmation: true,
    })
    render(<App />)
    const user = await startSession()
    expect(api.start).toHaveBeenCalledWith('test-key', 'Checkout is slow')
    await user.type(
      screen.getByLabelText('Report evidence or answer the current question'),
      'Production environment',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() =>
      expect(api.respond).toHaveBeenCalledWith(
        'test-key',
        expect.objectContaining({ version: 1 }),
        'Production environment',
      ),
    )
    await screen.findByText('Operator checkpoint')
  })

  it('preserves a failed draft and requires reload before another submission', async () => {
    vi.mocked(api.respond).mockRejectedValue(
      new ApiError(409, 'Session changed; reload its state.'),
    )
    vi.mocked(api.load).mockResolvedValue({ ...initial, version: 2 })
    render(<App />)
    const user = await startSession()
    await user.type(
      screen.getByLabelText('Report evidence or answer the current question'),
      'Production',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Session changed; reload its state.')
    expect(
      screen.getByLabelText('Report evidence or answer the current question'),
    ).toHaveValue('Production')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    await user.click(
      screen.getByRole('button', { name: 'Reload session before continuing' }),
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled(),
    )
  })

  it('confirms escalation and closes the composer without claiming a ticket', async () => {
    vi.mocked(api.respond).mockResolvedValue({
      ...initial,
      status: 'escalated',
      version: 2,
      current_step: null,
    })
    render(<App />)
    const user = await startSession()
    await user.click(
      screen.getByRole('button', { name: 'Escalate to an operator' }),
    )
    expect(screen.getByRole('dialog')).toHaveTextContent(
      'no external ticket is created',
    )
    await user.click(screen.getByRole('button', { name: 'Confirm escalation' }))
    await screen.findByText(
      'Evidence is saved. No external ticket has been created.',
    )
    expect(
      screen.queryByLabelText('Report evidence or answer the current question'),
    ).not.toBeInTheDocument()
    expect(api.respond).toHaveBeenCalledWith(
      'test-key',
      expect.objectContaining({ version: 1 }),
      '/escalate',
    )
  })

  it('resumes a backend session by ID', async () => {
    vi.mocked(api.load).mockResolvedValue(initial)
    render(<App />)
    const user = await connect()
    await user.click(screen.getByRole('button', { name: 'Resume a session' }))
    await user.type(screen.getByLabelText('Session ID'), 'session-one')
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', {
        name: 'Resume session',
      }),
    )
    await screen.findByText('Which environment is affected?')
    expect(api.load).toHaveBeenCalledWith('test-key', 'session-one')
  })

  it('clears credentials and session evidence on disconnect', async () => {
    render(<App />)
    const user = await startSession()
    await user.click(
      screen.getByRole('button', { name: 'Disconnect and clear workspace' }),
    )
    expect(screen.getByText('Connect API')).toBeInTheDocument()
    expect(
      screen.queryByText('Which environment is affected?'),
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Connect API' }))
    expect(screen.getByLabelText('Application API key')).toHaveValue('')
  })

  it('shows a readiness warning rather than suggesting the backend is operational', async () => {
    vi.mocked(api.readiness).mockResolvedValue({
      status: 'not_ready',
      checks: { llm_configured: false },
    })
    render(<App />)
    await connect()
    expect(screen.getByRole('status')).toHaveTextContent(
      'configuration is not ready',
    )
  })

  it('surfaces authentication failures without showing a connected state', async () => {
    vi.mocked(api.catalog).mockRejectedValue(
      new ApiError(401, 'Invalid or missing API key'),
    )
    render(<App />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Connect API' }))
    await user.click(screen.getByRole('button', { name: 'Connect securely' }))
    await waitFor(() =>
      expect(screen.getByRole('dialog')).toHaveTextContent(
        'Invalid or missing API key',
      ),
    )
    expect(screen.queryByText('API connected')).not.toBeInTheDocument()
  })
})
