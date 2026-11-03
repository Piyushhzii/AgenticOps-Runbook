import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('API boundary', () => {
  it('explains empty proxy failures when the backend is unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('', { status: 500 })),
    )
    await expect(api.catalog('')).rejects.toThrow(
      'Check that the Python backend is running',
    )
  })

  it('sends an application key only to the same-origin API proxy', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ items: [] })))
    vi.stubGlobal('fetch', fetchMock)
    await api.catalog('test-key')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/runbooks',
      expect.objectContaining({
        headers: { 'X-API-Key': 'test-key' },
        cache: 'no-store',
        credentials: 'omit',
      }),
    )
  })

  it('rejects a malformed response instead of rendering fabricated defaults', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('{"items":false}')),
    )
    await expect(api.catalog('')).rejects.toThrow('unexpected response')
  })

  it('reports network errors with an actionable message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    )
    await expect(api.catalog('')).rejects.toThrow('Cannot reach the API')
  })

  it('surfaces validation errors without assuming a string detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('{"detail":[{"msg":"invalid"}]}', { status: 422 }),
        ),
    )
    await expect(api.catalog('')).rejects.toThrow('Request failed (422)')
  })
})
