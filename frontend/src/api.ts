const BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body?.error?.message || `请求失败（${response.status}）`)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export const api = request

export const post = <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body || {}) })
export const patch = <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
export const remove = (path: string) => request<void>(path, { method: 'DELETE' })

export async function downloadFile(path: string, fallbackName: string): Promise<string> {
  const response = await fetch(`${BASE}${path}`, { headers: { Accept: 'text/csv' } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body?.error?.message || `下载失败（${response.status}）`)
  }
  const disposition = response.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/i)
  const filename = match?.[1] || fallbackName
  const objectUrl = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
  return filename
}
