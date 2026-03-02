export interface TunnelStatus {
  id: string
  service_url: string
  label: string
  name: string | null
  auth_mode: 'sso' | 'none'
  verify_ssl: boolean
  websocket_enabled: boolean
  api_key: string | null
  upstream_basic_auth: string | null
  forward_host: boolean
  subdomain: string | null
  state: 'CONNECTED' | 'CONNECTING' | 'STOPPED' | 'FAILED'
  error: string | null
  public_url: string | null
  pid: number | null
}

export interface UpdateTunnelRequest {
  service_url?: string
  label?: string
  name?: string
  auth_mode?: 'sso' | 'none'
  verify_ssl?: boolean
  websocket_enabled?: boolean
  api_key?: string | null
  upstream_basic_auth?: string | null
  forward_host?: boolean
}

export interface AccessRule {
  id: number
  allowed_email: string
  provider: string
  created_at: string
}

export interface PinStatus {
  has_pin: boolean
  updated_at: string | null
}

export interface BasicAuthStatus {
  has_basic_auth: boolean
  username: string | null
  updated_at: string | null
}

export interface ShareLink {
  id: number
  label: string
  token_prefix: string
  share_url: string
  expires_at: string
  max_uses: number | null
  use_count: number
  is_active: boolean
}

export interface AddonConfig {
  api_key_set: boolean
  api_key_masked: string
}

const base = './api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// Tunnels
export const getTunnels = () => request<TunnelStatus[]>('/tunnels')
export const addTunnel = (body: { service_url: string; label: string; name?: string; auth_mode: string; verify_ssl?: boolean; websocket_enabled?: boolean; api_key?: string; upstream_basic_auth?: string; forward_host?: boolean }) =>
  request<TunnelStatus>('/tunnels', { method: 'POST', body: JSON.stringify(body) })
export const updateTunnel = (id: string, body: UpdateTunnelRequest) =>
  request<TunnelStatus>(`/tunnels/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
export const removeTunnel = (id: string) => request<void>(`/tunnels/${id}`, { method: 'DELETE' })
export const startTunnel = (id: string) => request<void>(`/tunnels/${id}/start`, { method: 'POST' })
export const stopTunnel = (id: string) => request<void>(`/tunnels/${id}/stop`, { method: 'POST' })
export const getTunnelLogs = (id: string, lines = 200) =>
  request<{ lines: string[] }>(`/tunnels/${id}/logs?lines=${lines}`)

// Access rules
export const getAccessRules = (subdomain: string) => request<AccessRule[]>(`/tunnels/${subdomain}/access`)
export const addAccessRule = (subdomain: string, email: string, provider: string) =>
  request<AccessRule>(`/tunnels/${subdomain}/access`, { method: 'POST', body: JSON.stringify({ email, provider }) })
export const deleteAccessRule = (subdomain: string, ruleId: number) =>
  request<void>(`/tunnels/${subdomain}/access/${ruleId}`, { method: 'DELETE' })

// PIN
export const getPinStatus = (subdomain: string) => request<PinStatus>(`/tunnels/${subdomain}/pin`)
export const setPin = (subdomain: string, pin: string) =>
  request<void>(`/tunnels/${subdomain}/pin`, { method: 'PUT', body: JSON.stringify({ pin }) })
export const removePin = (subdomain: string) => request<void>(`/tunnels/${subdomain}/pin`, { method: 'DELETE' })

// Basic auth
export const getBasicAuthStatus = (subdomain: string) => request<BasicAuthStatus>(`/tunnels/${subdomain}/basic-auth`)
export const setBasicAuth = (subdomain: string, username: string, password: string) =>
  request<void>(`/tunnels/${subdomain}/basic-auth`, { method: 'PUT', body: JSON.stringify({ username, password }) })
export const removeBasicAuth = (subdomain: string) => request<void>(`/tunnels/${subdomain}/basic-auth`, { method: 'DELETE' })

// Share links
export const getShareLinks = (subdomain: string) => request<ShareLink[]>(`/tunnels/${subdomain}/share`)
export const createShareLink = (subdomain: string, body: { duration: string; label: string; max_uses?: number }) =>
  request<{ share_url: string; link: ShareLink }>(`/tunnels/${subdomain}/share`, { method: 'POST', body: JSON.stringify(body) })
export const deleteShareLink = (subdomain: string, linkId: number) =>
  request<void>(`/tunnels/${subdomain}/share/${linkId}`, { method: 'DELETE' })

// Config
export const getConfig = () => request<AddonConfig>('/config')
export const updateConfig = (api_key: string) =>
  request<void>('/config', { method: 'POST', body: JSON.stringify({ api_key }) })
