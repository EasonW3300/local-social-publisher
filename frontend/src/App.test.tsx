import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('App', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/api/submissions')) return response({ items: [] })
        throw new Error(`unexpected fetch: ${String(input)}`)
      }),
    )
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('offers the required image, title, copy, and platform controls', async () => {
    render(<App />)
    expect(screen.getByLabelText('标题')).toHaveAttribute('maxlength', '20')
    expect(screen.getByLabelText('文案')).toHaveAttribute('maxlength', '2000')
    expect(screen.getByLabelText('选择图片')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /微信公众号/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /CSDN/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('supports selecting a single platform and generating its preview', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/submissions')) return response({ items: [] })
      if (url.endsWith('/api/previews')) {
        return response({
          items: [{ platform: 'wechat', title: '测试标题', body: '<p>正文</p>', content_type: 'text/html', warnings: [] }],
        })
      }
      throw new Error(url)
    })
    render(<App />)
    await user.click(screen.getByRole('button', { name: /CSDN/ }))
    await user.type(screen.getByLabelText('标题'), '测试标题')
    await user.type(screen.getByLabelText('文案'), '正文')
    await user.upload(screen.getByLabelText('选择图片'), new File(['image'], 'image.png', { type: 'image/png' }))
    await user.click(screen.getByRole('button', { name: '生成平台预览' }))

    expect(await screen.findByText('预览已生成，请确认后发布。')).toBeInTheDocument()
    const previewCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/previews'))
    const body = previewCall?.[1]?.body as FormData
    expect(body.get('platforms')).toBe('["wechat"]')
    expect(screen.getByRole('button', { name: '确认并发布' })).toBeEnabled()
  })

  it('submits a confirmed multi-platform publication and refreshes history', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    let submitted = false
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/previews')) {
        return response({
          items: [
            { platform: 'wechat', title: '测试', body: '<p>正文</p>', content_type: 'text/html', warnings: [] },
            { platform: 'csdn', title: '测试', body: '正文', content_type: 'text/markdown', warnings: [] },
          ],
        })
      }
      if (url.endsWith('/api/submissions') && init?.method === 'POST') {
        submitted = true
        return response({ post_id: 'post-1', job_ids: { wechat: 'w', csdn: 'c' }, fingerprint: 'f' }, 201)
      }
      if (url.endsWith('/api/submissions')) {
        return response({
          items: submitted
            ? [{ post: { id: 'post-1', title: '测试', source_markdown: '正文', created_at: new Date().toISOString(), scheduled_at: null }, jobs: [] }]
            : [],
        })
      }
      throw new Error(url)
    })
    render(<App />)
    await user.type(screen.getByLabelText('标题'), '测试')
    await user.type(screen.getByLabelText('文案'), '正文')
    await user.upload(screen.getByLabelText('选择图片'), new File(['image'], 'image.png', { type: 'image/png' }))
    await user.click(screen.getByRole('button', { name: '生成平台预览' }))
    await user.click(await screen.findByRole('button', { name: '确认并发布' }))

    expect(await screen.findByText('发布任务已创建，正在后台执行。')).toBeInTheDocument()
    expect(await screen.findByText('测试')).toBeInTheDocument()
  })
})
