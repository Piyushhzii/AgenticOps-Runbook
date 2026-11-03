import { z } from 'zod'

const messageSchema = z.object({
  role: z.string(),
  message: z.string(),
  step_id: z.string().nullable().optional(),
  created_at: z.string(),
})
export const sessionSchema = z.object({
  session_id: z.string(),
  user_issue: z.string(),
  runbook_id: z.string(),
  status: z.enum(['active', 'completed', 'escalated']),
  version: z.number().int(),
  awaiting_user_input: z.boolean(),
  awaiting_confirmation: z.boolean(),
  current_step: z
    .object({
      step_id: z.string(),
      step_order: z.number(),
      instruction: z.string(),
      step_type: z.string(),
      next_steps: z.array(z.string()).nullable().optional(),
    })
    .nullable(),
  executed_steps: z.array(z.string()),
  context: z.record(z.string(), z.unknown()),
  messages: z.array(messageSchema),
  trace: z.array(z.string()),
})
export type Session = z.infer<typeof sessionSchema>
const catalogSchema = z.object({
  items: z.array(z.object({ runbook_id: z.string(), description: z.string() })),
})
export type Runbook = z.infer<typeof catalogSchema>['items'][number]
const readinessSchema = z.object({
  status: z.string(),
  checks: z.record(z.string(), z.boolean()),
})
export type Readiness = z.infer<typeof readinessSchema>

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request(path: string, key: string, body?: unknown) {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        ...(key ? { 'X-API-Key': key } : {}),
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(180_000),
      cache: 'no-store',
      credentials: 'omit',
    })
  } catch (error) {
    throw new ApiError(
      0,
      error instanceof DOMException && error.name === 'TimeoutError'
        ? 'The request timed out. Reload the session before retrying; the server may have saved the turn.'
        : 'Cannot reach the API. Check the backend and proxy connection.',
    )
  }
  const data: unknown = await response.json().catch(() => {
    throw new ApiError(
      response.status,
      response.status >= 500
        ? `The API or its proxy failed (${response.status}). Check that the Python backend is running on the configured port and inspect its logs.`
        : 'The server returned a non-JSON response. Check the API proxy.',
    )
  })
  if (!response.ok) {
    const parsed = z.object({ detail: z.string() }).safeParse(data)
    throw new ApiError(
      response.status,
      parsed.success
        ? parsed.data.detail
        : `Request failed (${response.status}).`,
    )
  }
  return data
}

function decode<T>(schema: z.ZodType<T>, data: unknown): T {
  const parsed = schema.safeParse(data)
  if (!parsed.success)
    throw new ApiError(
      502,
      'The API returned an unexpected response. Check frontend/backend version compatibility.',
    )
  return parsed.data
}

export const api = {
  async catalog(key: string) {
    return decode(catalogSchema, await request('/runbooks', key)).items
  },
  async readiness(key: string): Promise<Readiness> {
    try {
      return decode(readinessSchema, await request('/ready', key))
    } catch (error) {
      if (error instanceof ApiError && error.status === 503) {
        return { status: 'not_ready', checks: { configuration: false } }
      }
      throw error
    }
  },
  async start(key: string, issue: string) {
    return decode(sessionSchema, await request('/sessions', key, { issue }))
  },
  async load(key: string, id: string) {
    return decode(
      sessionSchema,
      await request(`/sessions/${encodeURIComponent(id)}`, key),
    )
  },
  async respond(key: string, session: Session, message: string) {
    return decode(
      sessionSchema,
      await request(
        `/sessions/${encodeURIComponent(session.session_id)}/responses`,
        key,
        {
          message,
          expected_version: session.version,
        },
      ),
    )
  },
}

export function title(id: string) {
  return id
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
