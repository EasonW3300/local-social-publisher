import type {
  AssetUsage,
  Platform,
  PreviewItem,
  SubmissionListItem,
  WeChatSettings,
} from './types'

export interface PublishForm {
  title: string
  markdown: string
  image: File
  platforms: Platform[]
  imageUsage: Record<Platform, AssetUsage>
  scheduledAt: string
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(message)
  }
}

let localTokenPromise: Promise<string> | undefined

async function localToken(): Promise<string> {
  if (!localTokenPromise) {
    localTokenPromise = fetch('/api/session')
      .then(checked)
      .then(async (response) => (await response.json()).token as string)
      .catch((error) => {
        localTokenPromise = undefined
        throw error
      })
  }
  return localTokenPromise
}

async function writeRequest(url: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('X-Local-Publisher-Token', await localToken())
  return fetch(url, { ...init, headers })
}

function formData(values: PublishForm, confirmDuplicate = false): FormData {
  const data = new FormData()
  data.set('title', values.title)
  data.set('markdown', values.markdown)
  data.set('image', values.image)
  data.set('platforms', JSON.stringify(values.platforms))
  data.set(
    'image_usage',
    JSON.stringify(
      Object.fromEntries(values.platforms.map((platform) => [platform, values.imageUsage[platform]])),
    ),
  )
  if (values.scheduledAt) data.set('scheduled_at', new Date(values.scheduledAt).toISOString())
  data.set('confirm_duplicate', String(confirmDuplicate))
  return data
}

async function checked(response: Response): Promise<Response> {
  if (response.ok) return response
  let detail: unknown
  try {
    detail = await response.json()
  } catch {
    detail = await response.text()
  }
  throw new ApiError(`请求失败（${response.status}）`, response.status, detail)
}

export async function preview(values: PublishForm): Promise<PreviewItem[]> {
  const response = await checked(
    await writeRequest('/api/previews', { method: 'POST', body: formData(values) }),
  )
  return (await response.json()).items
}

export async function submit(values: PublishForm, confirmDuplicate = false): Promise<string> {
  const response = await checked(
    await writeRequest('/api/submissions', {
      method: 'POST',
      body: formData(values, confirmDuplicate),
    }),
  )
  return (await response.json()).post_id
}

export async function listSubmissions(): Promise<SubmissionListItem[]> {
  const response = await checked(await fetch('/api/submissions'))
  return (await response.json()).items
}

export async function getWeChatSettings(): Promise<WeChatSettings> {
  const response = await checked(await fetch('/api/settings/wechat'))
  return response.json()
}

export async function saveWeChatSettings(values: {
  app_id: string
  app_secret?: string
  browser_fallback_enabled: boolean
}): Promise<WeChatSettings> {
  const response = await checked(
    await writeRequest('/api/settings/wechat', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    }),
  )
  return response.json()
}

export async function openPlatformLogin(platform: Platform): Promise<void> {
  await checked(await writeRequest(`/api/browser/${platform}/login`, { method: 'POST' }))
}

export async function retryJob(jobId: string): Promise<void> {
  await checked(await writeRequest(`/api/jobs/${jobId}/retry`, { method: 'POST' }))
}

export async function checkCsdnLogin(): Promise<boolean> {
  const response = await checked(
    await writeRequest('/api/browser/csdn/status', { method: 'POST' }),
  )
  return (await response.json()).logged_in as boolean
}
