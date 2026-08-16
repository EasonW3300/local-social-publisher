import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
        if (String(input).endsWith('/api/session')) return response({ token: 'local-token' })
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
      if (url.endsWith('/api/session')) return response({ token: 'local-token' })
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
      if (url.endsWith('/api/session')) return response({ token: 'local-token' })
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
      if (url.endsWith('/api/settings/wechat')) {
        return response({ app_id: '', secret_configured: false, official_configured: false, browser_fallback_enabled: false })
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

  it('serializes a local appointment and creates a scheduled submission', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/session')) return response({ token: 'local-token' })
      if (url.endsWith('/api/previews')) {
        return response({
          items: [
            { platform: 'wechat', title: '预约测试', body: '<p>正文</p>', content_type: 'text/html', warnings: [] },
            { platform: 'csdn', title: '预约测试', body: '正文', content_type: 'text/markdown', warnings: [] },
          ],
        })
      }
      if (url.endsWith('/api/submissions') && init?.method === 'POST') {
        return response({ post_id: 'scheduled', job_ids: { wechat: 'w', csdn: 'c' }, fingerprint: 'f' }, 201)
      }
      if (url.endsWith('/api/submissions')) return response({ items: [] })
      if (url.endsWith('/api/settings/wechat')) {
        return response({ app_id: '', secret_configured: false, official_configured: false, browser_fallback_enabled: false })
      }
      throw new Error(url)
    })

    render(<App />)
    await user.type(screen.getByLabelText('标题'), '预约测试')
    await user.type(screen.getByLabelText('文案'), '正文')
    await user.upload(screen.getByLabelText('选择图片'), new File(['image'], 'image.png', { type: 'image/png' }))
    fireEvent.change(screen.getByLabelText('预约时间'), { target: { value: '2026-08-17T10:00' } })
    await user.click(screen.getByRole('button', { name: '生成平台预览' }))
    await user.click(await screen.findByRole('button', { name: '确认并预约' }))

    expect(await screen.findByText('预约任务已创建。')).toBeInTheDocument()
    const request = fetchMock.mock.calls.find(([url, init]) =>
      String(url).endsWith('/api/submissions') && init?.method === 'POST',
    )
    const body = request?.[1]?.body as FormData
    expect(body.get('scheduled_at')).toBe(new Date('2026-08-17T10:00').toISOString())
  })

  it('saves WeChat credentials without rendering the secret back', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/session')) return response({ token: 'local-token' })
      if (url.endsWith('/api/submissions')) return response({ items: [] })
      if (url.endsWith('/api/settings/wechat') && init?.method === 'PUT') {
        return response({ app_id: 'wx-app', secret_configured: true, official_configured: true, browser_fallback_enabled: true })
      }
      if (url.endsWith('/api/settings/wechat')) {
        return response({ app_id: '', secret_configured: false, official_configured: false, browser_fallback_enabled: false })
      }
      throw new Error(url)
    })
    render(<App />)
    await user.click(screen.getByRole('button', { name: '账号设置' }))
    await user.type(screen.getByLabelText('微信公众号 AppID'), 'wx-app')
    await user.type(screen.getByLabelText('微信公众号 AppSecret'), 'top-secret')
    await user.click(screen.getByText('官方接口无权限时启用浏览器降级'))
    await user.click(screen.getByRole('button', { name: '安全保存' }))

    expect(await screen.findByText('账号设置已安全保存。')).toBeInTheDocument()
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(request?.[1]?.body).toContain('top-secret')
    expect(screen.queryByDisplayValue('top-secret')).not.toBeInTheDocument()
  })

  it('lets the user resume a job after completing interactive login', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/session')) return response({ token: 'local-token' })
      if (url.endsWith('/api/jobs/csdn-job/retry') && init?.method === 'POST') {
        return response({ status: 'ready' }, 202)
      }
      if (url.endsWith('/api/submissions')) {
        return response({
          items: [{
            post: { id: 'post-1', title: '待登录文章', source_markdown: '正文', created_at: new Date().toISOString(), scheduled_at: null },
            jobs: [{ id: 'csdn-job', platform: 'csdn', status: 'waiting_user', result_url: null, error_message: null, scheduled_at: null }],
          }],
        })
      }
      if (url.endsWith('/api/settings/wechat')) {
        return response({ app_id: '', secret_configured: false, official_configured: false, browser_fallback_enabled: false })
      }
      throw new Error(url)
    })

    render(<App />)
    await user.click(await screen.findByText('待登录文章'))
    await user.click(screen.getByRole('button', { name: '已登录，继续' }))

    expect(await screen.findByText('任务已重新进入执行队列。')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/jobs/csdn-job/retry',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('checks and displays the CSDN browser login state', async () => {
    const user = userEvent.setup()
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/session')) return response({ token: 'local-token' })
      if (url.endsWith('/api/browser/csdn/status') && init?.method === 'POST') {
        return response({ logged_in: true })
      }
      if (url.endsWith('/api/submissions')) return response({ items: [] })
      if (url.endsWith('/api/settings/wechat')) {
        return response({ app_id: '', secret_configured: false, official_configured: false, browser_fallback_enabled: false })
      }
      throw new Error(url)
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: '账号设置' }))
    await user.click(screen.getByRole('button', { name: '检查 CSDN 登录' }))

    expect(await screen.findByText('CSDN 已登录')).toBeInTheDocument()
  })

  it('checks WeChat API readiness without publishing content', async () => {
    const user = userEvent.setup()
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/session')) return response({ token: 'local-token' })
      if (url.endsWith('/api/settings/wechat/status') && init?.method === 'POST') {
        return response({ ready: true, code: null, message: '微信公众号官方 API 凭证与网络检查通过' })
      }
      if (url.endsWith('/api/submissions')) return response({ items: [] })
      if (url.endsWith('/api/settings/wechat')) {
        return response({ app_id: 'wx-app', secret_configured: true, official_configured: true, browser_fallback_enabled: false })
      }
      throw new Error(url)
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: '账号设置' }))
    await user.click(screen.getByRole('button', { name: '检查微信 API' }))

    expect(await screen.findByText('微信 API 可用')).toBeInTheDocument()
    expect(await screen.findByText('微信公众号官方 API 凭证与网络检查通过')).toBeInTheDocument()
  })
})
