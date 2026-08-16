export type Platform = 'wechat' | 'csdn'
export type AssetUsage = 'cover' | 'body' | 'both'

export interface PreviewItem {
  platform: Platform
  title: string
  body: string
  content_type: string
  warnings: string[]
}

export interface PlatformJob {
  id: string
  platform: Platform
  status: string
  result_url: string | null
  error_message: string | null
  scheduled_at: string | null
}

export interface SubmissionListItem {
  post: {
    id: string
    title: string
    source_markdown: string
    scheduled_at: string | null
    created_at: string
  }
  jobs: PlatformJob[]
}
