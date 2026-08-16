import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import {
  ApiError,
  getWeChatSettings,
  listSubmissions,
  openPlatformLogin,
  preview,
  retryJob,
  saveWeChatSettings,
  submit,
  type PublishForm,
} from './api'
import type {
  AssetUsage,
  Platform,
  PreviewItem,
  SubmissionListItem,
  WeChatSettings,
} from './types'
import './styles.css'

const PLATFORM_META: Record<Platform, { name: string; badge: string; detail: string }> = {
  wechat: { name: '微信公众号', badge: '微', detail: '官方 API 优先，保存公开链接' },
  csdn: { name: 'CSDN', badge: 'C', detail: '创建草稿并打开专用浏览器' },
}

const STATUS_LABEL: Record<string, string> = {
  ready: '等待执行',
  scheduled: '已预约',
  running: '执行中',
  pending_remote: '平台处理中',
  waiting_user: '等待人工',
  succeeded: '已完成',
  failed: '失败',
  unknown: '结果待核实',
  missed: '已错过',
  canceled: '已取消',
}

const defaultUsage: Record<Platform, AssetUsage> = { wechat: 'cover', csdn: 'body' }

export default function App() {
  const [title, setTitle] = useState('')
  const [markdown, setMarkdown] = useState('')
  const [image, setImage] = useState<File | null>(null)
  const [platforms, setPlatforms] = useState<Platform[]>(['wechat', 'csdn'])
  const [imageUsage, setImageUsage] = useState(defaultUsage)
  const [scheduledAt, setScheduledAt] = useState('')
  const [previews, setPreviews] = useState<PreviewItem[]>([])
  const [records, setRecords] = useState<SubmissionListItem[]>([])
  const [busy, setBusy] = useState<'preview' | 'publish' | null>(null)
  const [message, setMessage] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [wechatSettings, setWechatSettings] = useState<WeChatSettings | null>(null)
  const [wechatAppId, setWechatAppId] = useState('')
  const [wechatSecret, setWechatSecret] = useState('')
  const [browserFallback, setBrowserFallback] = useState(false)

  const values = useMemo<PublishForm | null>(() => {
    if (!image) return null
    return { title, markdown, image, platforms, imageUsage, scheduledAt }
  }, [image, imageUsage, markdown, platforms, scheduledAt, title])

  const refresh = useCallback(async () => {
    try {
      setRecords(await listSubmissions())
    } catch {
      // The composer remains usable while a transient refresh fails.
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 3000)
    return () => window.clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    void getWeChatSettings()
      .then((current) => {
        setWechatSettings(current)
        setWechatAppId(current.app_id)
        setBrowserFallback(current.browser_fallback_enabled)
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => setPreviews([]), [title, markdown, image, platforms, imageUsage, scheduledAt])

  function togglePlatform(platform: Platform) {
    setPlatforms((current) =>
      current.includes(platform)
        ? current.filter((value) => value !== platform)
        : [...current, platform],
    )
  }

  function validate(): PublishForm | null {
    setMessage('')
    if (!values || !title.trim() || !markdown.trim() || platforms.length === 0) {
      setMessage('请填写图片、标题和文案，并至少选择一个平台。')
      return null
    }
    return values
  }

  async function handlePreview() {
    const form = validate()
    if (!form) return
    setBusy('preview')
    try {
      setPreviews(await preview(form))
      setMessage('预览已生成，请确认后发布。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '预览失败')
    } finally {
      setBusy(null)
    }
  }

  async function handlePublish(event: FormEvent) {
    event.preventDefault()
    const form = validate()
    if (!form) return
    if (previews.length !== platforms.length) {
      setMessage('内容发生变化，请重新生成并确认平台预览。')
      return
    }
    setBusy('publish')
    try {
      await submit(form)
      setMessage(scheduledAt ? '预约任务已创建。' : '发布任务已创建，正在后台执行。')
      setPreviews([])
      await refresh()
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        const confirmed = window.confirm('检测到相同内容，仍然创建发布任务吗？')
        if (confirmed) {
          await submit(form, true)
          setMessage('重复内容已确认，发布任务已创建。')
          setPreviews([])
          await refresh()
        }
      } else {
        setMessage(error instanceof Error ? error.message : '发布失败')
      }
    } finally {
      setBusy(null)
    }
  }

  async function handleSaveSettings(event: FormEvent) {
    event.preventDefault()
    try {
      const current = await saveWeChatSettings({
        app_id: wechatAppId,
        app_secret: wechatSecret || undefined,
        browser_fallback_enabled: browserFallback,
      })
      setWechatSettings(current)
      setWechatSecret('')
      setMessage('账号设置已安全保存。')
      setSettingsOpen(false)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '账号设置保存失败')
    }
  }

  async function openLogin(platform: Platform) {
    try {
      await openPlatformLogin(platform)
      setMessage(`正在打开${PLATFORM_META[platform].name}专用登录窗口。`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '无法打开登录窗口')
    }
  }

  async function retry(jobId: string) {
    try {
      await retryJob(jobId)
      setMessage('任务已重新进入执行队列。')
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '任务无法重新执行')
    }
  }

  return (
    <main>
      <header className="masthead">
        <div>
          <p className="eyebrow">LOCAL SOCIAL PUBLISHER</p>
          <h1>把一次创作，稳稳送达。</h1>
          <p className="lead">本地运行、逐平台追踪。微信直发，CSDN 草稿终审。</p>
        </div>
        <div className="header-tools">
          <div className="privacy-pill"><span /> 凭证与内容仅保存在本机</div>
          <button className="settings-button" type="button" onClick={() => setSettingsOpen((value) => !value)}>
            账号设置
          </button>
        </div>
      </header>

      {settingsOpen && (
        <form className="settings-panel" onSubmit={handleSaveSettings}>
          <div className="settings-copy">
            <p>ACCOUNT SETUP</p>
            <h2>平台账号</h2>
            <span>密钥写入操作系统凭证库，页面和 SQLite 均不会返回明文。</span>
          </div>
          <div className="settings-fields">
            <label><span>微信公众号 AppID</span><input aria-label="微信公众号 AppID" value={wechatAppId} onChange={(event) => setWechatAppId(event.target.value)} placeholder="wx…" /></label>
            <label><span>AppSecret {wechatSettings?.secret_configured && <b>已配置</b>}</span><input aria-label="微信公众号 AppSecret" type="password" value={wechatSecret} onChange={(event) => setWechatSecret(event.target.value)} placeholder={wechatSettings?.secret_configured ? '留空则保持不变' : '输入 AppSecret'} /></label>
            <label className="fallback-check"><input type="checkbox" checked={browserFallback} onChange={(event) => setBrowserFallback(event.target.checked)} />官方接口无权限时启用浏览器降级</label>
          </div>
          <div className="settings-actions">
            <button type="button" onClick={() => void openLogin('wechat')}>打开微信登录</button>
            <button type="button" onClick={() => void openLogin('csdn')}>打开 CSDN 登录</button>
            <button className="save-settings" type="submit">安全保存</button>
          </div>
        </form>
      )}

      <section className="workspace">
        <form className="composer" onSubmit={handlePublish}>
          <div className="section-heading">
            <span>01</span><div><h2>内容</h2><p>标题、正文与一张主图</p></div>
          </div>

          <label className="field">
            <span>标题 <b>{title.length}/20</b></span>
            <input
              aria-label="标题"
              maxLength={20}
              placeholder="一句清晰、有辨识度的标题"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>

          <label className="field">
            <span>文案（Markdown） <b>{markdown.length}/2000</b></span>
            <textarea
              aria-label="文案"
              maxLength={2000}
              placeholder="支持标题、列表、粗体与链接……"
              value={markdown}
              onChange={(event) => setMarkdown(event.target.value)}
            />
          </label>

          <label className={`image-drop ${image ? 'has-file' : ''}`}>
            <input
              aria-label="选择图片"
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(event) => setImage(event.target.files?.[0] ?? null)}
            />
            <strong>{image ? image.name : '选择一张图片'}</strong>
            <span>{image ? `${(image.size / 1024).toFixed(1)} KB` : 'PNG、JPG、GIF 或 WebP，最大 10 MB'}</span>
          </label>

          <div className="section-heading destination-heading">
            <span>02</span><div><h2>发布目标</h2><p>可单选，也可多选</p></div>
          </div>
          <div className="platform-grid">
            {(Object.keys(PLATFORM_META) as Platform[]).map((platform) => {
              const selected = platforms.includes(platform)
              return (
                <div className={`platform-card ${selected ? 'selected' : ''}`} key={platform}>
                  <button type="button" onClick={() => togglePlatform(platform)} aria-pressed={selected}>
                    <i>{PLATFORM_META[platform].badge}</i>
                    <span><strong>{PLATFORM_META[platform].name}</strong><small>{PLATFORM_META[platform].detail}</small></span>
                    <em>{selected ? '已选择' : '选择'}</em>
                  </button>
                  {selected && (
                    <label>
                      图片用途
                      <select
                        aria-label={`${PLATFORM_META[platform].name}图片用途`}
                        value={imageUsage[platform]}
                        onChange={(event) => setImageUsage((current) => ({
                          ...current,
                          [platform]: event.target.value as AssetUsage,
                        }))}
                      >
                        <option value="cover">封面</option>
                        <option value="body">正文首图</option>
                        <option value="both">封面与正文</option>
                      </select>
                    </label>
                  )}
                </div>
              )
            })}
          </div>

          <label className="field schedule-field">
            <span>预约时间 <b>可选</b></span>
            <input
              aria-label="预约时间"
              type="datetime-local"
              value={scheduledAt}
              onChange={(event) => setScheduledAt(event.target.value)}
            />
          </label>

          {message && <p className="message" role="status">{message}</p>}
          <div className="actions">
            <button className="secondary" type="button" disabled={busy !== null} onClick={handlePreview}>
              {busy === 'preview' ? '生成中…' : '生成平台预览'}
            </button>
            <button className="primary" type="submit" disabled={busy !== null || previews.length === 0}>
              {busy === 'publish' ? '提交中…' : scheduledAt ? '确认并预约' : '确认并发布'}
            </button>
          </div>
        </form>

        <aside className="preview-panel">
          <div className="panel-title"><div><p>PLATFORM PREVIEW</p><h2>发布预览</h2></div><span>{previews.length}/{platforms.length}</span></div>
          {previews.length === 0 ? (
            <div className="empty-preview"><i>稿</i><strong>预览将在这里出现</strong><p>填写内容并选择目标平台，然后生成预览。</p></div>
          ) : previews.map((item) => (
            <article className="preview-card" key={item.platform}>
              <header><i>{PLATFORM_META[item.platform].badge}</i><strong>{PLATFORM_META[item.platform].name}</strong><span>已就绪</span></header>
              <h3>{item.title}</h3>
              {item.content_type === 'text/html'
                ? <div className="rendered" dangerouslySetInnerHTML={{ __html: item.body }} />
                : <pre>{item.body}</pre>}
            </article>
          ))}
        </aside>
      </section>

      <section className="history">
        <div className="history-title"><div><p>DELIVERY LOG</p><h2>发布记录</h2></div><button type="button" onClick={() => void refresh()}>刷新</button></div>
        {records.length === 0 ? <p className="empty-history">还没有发布记录。</p> : records.map((record) => (
          <details className="record" key={record.post.id}>
            <summary>
              <div><strong>{record.post.title}</strong><small>{new Date(record.post.created_at).toLocaleString()}</small></div>
              <div className="job-chips">{record.jobs.map((job) => <span className={`status-${job.status}`} key={job.id}>{PLATFORM_META[job.platform].name} · {STATUS_LABEL[job.status] ?? job.status}</span>)}</div>
            </summary>
            <div className="job-list">{record.jobs.map((job) => (
              <div key={job.id}><i>{PLATFORM_META[job.platform].badge}</i><span><strong>{PLATFORM_META[job.platform].name}</strong><small>{job.error_message ?? STATUS_LABEL[job.status] ?? job.status}</small></span>{job.result_url && <a href={job.result_url} target="_blank" rel="noreferrer">打开链接</a>}{['waiting_user', 'failed', 'missed'].includes(job.status) && <button type="button" onClick={() => void retry(job.id)}>{job.status === 'waiting_user' ? '已登录，继续' : '重新执行'}</button>}</div>
            ))}</div>
          </details>
        ))}
      </section>
    </main>
  )
}
