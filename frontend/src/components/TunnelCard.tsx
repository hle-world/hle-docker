import { useState, useEffect, useRef } from 'react'
import type { TunnelStatus, AccessRule, ShareLink, BasicAuthStatus } from '../api/client'
import {
  startTunnel, stopTunnel, removeTunnel, updateTunnel,
  getAccessRules, addAccessRule, deleteAccessRule,
  getPinStatus, setPin, removePin,
  getBasicAuthStatus, setBasicAuth, removeBasicAuth,
  getShareLinks, createShareLink, deleteShareLink,
  getTunnelLogs,
} from '../api/client'
import { StatusBadge } from './StatusBadge'

interface Props {
  tunnel: TunnelStatus
  onRefresh: () => void
}

const card: React.CSSProperties = {
  background: 'var(--bg-raised)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
  padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10,
}
const row: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }
const section: React.CSSProperties = {
  borderTop: '1px solid var(--border)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 8,
}
const sectionTitle: React.CSSProperties = { fontSize: 13, fontWeight: 600, color: 'var(--text-dim)', marginBottom: 2 }
const btn = (variant: 'primary' | 'danger' | 'ghost' | 'active'): React.CSSProperties => ({
  padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
  fontFamily: 'inherit',
  background: variant === 'primary' ? 'var(--mint)' : variant === 'danger' ? 'var(--red)' : variant === 'active' ? 'var(--mint-dim)' : 'var(--surface)',
  color: variant === 'primary' || variant === 'active' ? 'var(--bg)' : variant === 'danger' ? '#fff' : 'var(--text-dim)',
  whiteSpace: 'nowrap',
})
const inputSm: React.CSSProperties = {
  padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'var(--bg)', color: 'var(--text)', fontSize: 13, fontFamily: 'inherit',
}
const inputErr: React.CSSProperties = {
  ...inputSm, borderColor: 'var(--red)',
}
const warningBox: React.CSSProperties = {
  background: 'var(--yellow-tint-bg)', border: '1px solid var(--yellow-tint-border)', borderRadius: 6,
  padding: '8px 12px', fontSize: 13, color: 'var(--yellow)',
}
const confirmBox: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border-hi)', borderRadius: 6,
  padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8,
}

type Panel = 'access' | 'pin' | 'basic-auth' | 'share' | 'logs' | 'edit' | null

export function TunnelCard({ tunnel, onRefresh }: Props) {
  const [panel, setPanel] = useState<Panel>(null)
  const [error, setError] = useState('')
  const [urlCopied, setUrlCopied] = useState(false)

  // Access rules state
  const [rules, setRules] = useState<AccessRule[] | null>(null)
  const [newEmail, setNewEmail] = useState('')
  const [newProvider, setNewProvider] = useState('any')

  // PIN state
  const [hasPin, setHasPin] = useState<boolean | null>(null)
  const [newPin, setNewPin] = useState('')
  const [confirmPin, setConfirmPin] = useState('')

  // Basic auth state
  const [basicAuth, setBasicAuthState] = useState<BasicAuthStatus | null>(null)
  const [baUsername, setBaUsername] = useState('')
  const [baPassword, setBaPassword] = useState('')
  const [baConfirmPassword, setBaConfirmPassword] = useState('')

  // Conflict warning acknowledgement (reset when panel changes)
  const [conflictAcked, setConflictAcked] = useState(false)

  // Confirmation dialog for destructive actions
  const [confirmAction, setConfirmAction] = useState<{ message: string; onConfirm: () => void } | null>(null)

  // Share links state
  const [shareLinks, setShareLinks] = useState<ShareLink[] | null>(null)
  const [shareDuration, setShareDuration] = useState<'1h' | '24h' | '7d'>('24h')
  const [shareLabel, setShareLabel] = useState('')
  const [newShareUrl, setNewShareUrl] = useState<string | null>(null)

  // Logs state
  const [logs, setLogs] = useState<string[] | null>(null)
  const logsRef = useRef<HTMLPreElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  // Auto-refresh logs when panel is open
  useEffect(() => {
    if (panel !== 'logs') return
    const fetchLogs = async () => {
      try {
        const result = await getTunnelLogs(tunnel.id)
        setLogs(result.lines)
      } catch { /* ignore */ }
    }
    const id = setInterval(fetchLogs, 3000)
    return () => clearInterval(id)
  }, [panel, tunnel.id])

  // Auto-scroll logs to bottom when new content arrives (only if enabled)
  useEffect(() => {
    if (autoScroll && logsRef.current) {
      logsRef.current.scrollTop = logsRef.current.scrollHeight
    }
  }, [logs])

  // Detect when user scrolls up (disable) or back to bottom (re-enable)
  function handleLogsScroll() {
    if (!logsRef.current) return
    const el = logsRef.current
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20
    setAutoScroll(atBottom)
  }

  // Edit state (mirrors current tunnel values)
  const [editServiceUrl, setEditServiceUrl] = useState(tunnel.service_url)
  const [editLabel, setEditLabel] = useState(tunnel.label)
  const [editName, setEditName] = useState(tunnel.name ?? '')
  const [editAuthMode, setEditAuthMode] = useState<'sso' | 'none'>(tunnel.auth_mode)
  const [editVerifySsl, setEditVerifySsl] = useState(tunnel.verify_ssl)
  const [editWebsocket, setEditWebsocket] = useState(tunnel.websocket_enabled)
  const [editApiKey, setEditApiKey] = useState(tunnel.api_key ?? '')
  const [editUpstreamBasicAuth, setEditUpstreamBasicAuth] = useState(tunnel.upstream_basic_auth ?? '')
  const [editForwardHost, setEditForwardHost] = useState(tunnel.forward_host)
  const [editResponseTimeout, setEditResponseTimeout] = useState(tunnel.response_timeout?.toString() ?? '')
  const [editSaving, setEditSaving] = useState(false)

  const sub = tunnel.subdomain
  const [faviconOk, setFaviconOk] = useState(false)
  const [faviconChecked, setFaviconChecked] = useState(false)

  // Retry favicon when tunnel becomes CONNECTED
  useEffect(() => {
    if (tunnel.state === 'CONNECTED' && !faviconChecked) {
      setFaviconOk(true)
      setFaviconChecked(true)
    }
    if (tunnel.state !== 'CONNECTED') {
      setFaviconChecked(false)
    }
  }, [tunnel.state, faviconChecked])

  async function togglePanel(p: Panel) {
    setError('')
    setNewShareUrl(null)
    setConflictAcked(false)
    setConfirmAction(null)
    if (panel === p) { setPanel(null); return }
    // Reset form fields when opening panels
    if (p === 'edit') {
      setEditServiceUrl(tunnel.service_url)
      setEditLabel(tunnel.label)
      setEditName(tunnel.name ?? '')
      setEditAuthMode(tunnel.auth_mode)
      setEditVerifySsl(tunnel.verify_ssl)
      setEditWebsocket(tunnel.websocket_enabled)
      setEditApiKey(tunnel.api_key ?? '')
      setEditUpstreamBasicAuth(tunnel.upstream_basic_auth ?? '')
      setEditForwardHost(tunnel.forward_host)
      setEditResponseTimeout(tunnel.response_timeout?.toString() ?? '')
    }
    if (p === 'pin') { setNewPin(''); setConfirmPin('') }
    if (p === 'basic-auth') { setBaUsername(''); setBaPassword(''); setBaConfirmPassword('') }
    if (p === 'access') { setNewEmail(''); setNewProvider('any') }
    setPanel(p)
    if (!sub) return
    try {
      if (p === 'access') {
        const [rulesRes, baRes] = await Promise.all([
          rules === null ? getAccessRules(sub) : Promise.resolve(rules),
          basicAuth === null ? getBasicAuthStatus(sub).catch(() => null) : Promise.resolve(basicAuth),
        ])
        if (rules === null) setRules(rulesRes)
        if (baRes) setBasicAuthState(baRes)
      }
      if (p === 'pin') {
        const [pinRes, baRes] = await Promise.all([
          hasPin === null ? getPinStatus(sub) : Promise.resolve(null),
          basicAuth === null ? getBasicAuthStatus(sub).catch(() => null) : Promise.resolve(basicAuth),
        ])
        if (pinRes) setHasPin(pinRes.has_pin)
        if (baRes) setBasicAuthState(baRes)
      }
      if (p === 'basic-auth') {
        const [baRes, pinRes, rulesRes] = await Promise.all([
          basicAuth === null ? getBasicAuthStatus(sub) : Promise.resolve(basicAuth),
          hasPin === null ? getPinStatus(sub).catch(() => null) : Promise.resolve(null),
          rules === null ? getAccessRules(sub).catch(() => null) : Promise.resolve(rules),
        ])
        if (basicAuth === null) setBasicAuthState(baRes)
        if (pinRes) setHasPin(pinRes.has_pin)
        if (rulesRes && rules === null) setRules(rulesRes)
      }
      if (p === 'share' && shareLinks === null) setShareLinks(await getShareLinks(sub))
      if (p === 'logs') {
        setAutoScroll(true)
        setLogs((await getTunnelLogs(tunnel.id)).lines)
      }
    } catch (e) { setError(String(e)) }
  }

  async function handleSaveEdit() {
    setEditSaving(true)
    setError('')
    try {
      await updateTunnel(tunnel.id, {
        service_url: editServiceUrl,
        label: editLabel,
        name: editName || undefined,
        auth_mode: editAuthMode,
        verify_ssl: editVerifySsl,
        websocket_enabled: editWebsocket,
        api_key: editApiKey || null,
        upstream_basic_auth: editUpstreamBasicAuth || null,
        forward_host: editForwardHost,
        response_timeout: editResponseTimeout ? parseInt(editResponseTimeout, 10) : null,
      })
      setPanel(null)
      onRefresh()
    } catch (e) {
      setError(String(e))
    } finally {
      setEditSaving(false)
    }
  }

  // --- Access rules handlers ---

  async function handleAddRule() {
    if (!sub || !newEmail) return
    try {
      const rule = await addAccessRule(sub, newEmail, newProvider)
      setRules(prev => [...(prev ?? []), rule])
      setNewEmail('')
    } catch (e) { setError(String(e)) }
  }

  function handleDeleteRule(id: number) {
    setConfirmAction({
      message: 'Remove this email from the allow-list?',
      onConfirm: async () => {
        if (!sub) return
        await deleteAccessRule(sub, id)
        setRules(prev => (prev ?? []).filter(r => r.id !== id))
        setConfirmAction(null)
      },
    })
  }

  // --- PIN handlers ---

  const pinValid = /^\d{4,8}$/.test(newPin)
  const pinMatch = newPin === confirmPin
  const pinTouched = newPin.length > 0
  const confirmPinTouched = confirmPin.length > 0

  async function handleSetPin() {
    if (!sub || !pinValid || !pinMatch) return
    try {
      await setPin(sub, newPin)
      setHasPin(true)
      setNewPin('')
      setConfirmPin('')
    } catch (e) { setError(String(e)) }
  }

  function handleRemovePin() {
    setConfirmAction({
      message: 'Remove PIN from this tunnel?',
      onConfirm: async () => {
        if (!sub) return
        await removePin(sub)
        setHasPin(false)
        setConfirmAction(null)
      },
    })
  }

  // --- Basic auth handlers ---

  const baUsernameValid = baUsername.length > 0 && !baUsername.includes(':')
  const baPasswordValid = baPassword.length >= 8
  const baPasswordMatch = baPassword === baConfirmPassword
  const baUsernameTouched = baUsername.length > 0
  const baPasswordTouched = baPassword.length > 0
  const baConfirmTouched = baConfirmPassword.length > 0

  async function handleSetBasicAuth() {
    if (!sub || !baUsernameValid || !baPasswordValid || !baPasswordMatch) return
    try {
      await setBasicAuth(sub, baUsername, baPassword)
      setBasicAuthState(await getBasicAuthStatus(sub))
      setBaUsername('')
      setBaPassword('')
      setBaConfirmPassword('')
    } catch (e) { setError(String(e)) }
  }

  function handleRemoveBasicAuth() {
    setConfirmAction({
      message: 'Remove Basic Auth from this tunnel?',
      onConfirm: async () => {
        if (!sub) return
        await removeBasicAuth(sub)
        setBasicAuthState({ has_basic_auth: false, username: null, updated_at: null })
        setConfirmAction(null)
      },
    })
  }

  async function handleCreateShare() {
    if (!sub) return
    try {
      const result = await createShareLink(sub, { duration: shareDuration, label: shareLabel })
      setNewShareUrl(result.share_url)
      setShareLinks(await getShareLinks(sub))
    } catch (e) { setError(String(e)) }
  }

  async function handleDeleteShare(id: number) {
    if (!sub) return
    await deleteShareLink(sub, id)
    setShareLinks(prev => (prev ?? []).filter(l => l.id !== id))
  }

  const isSso = tunnel.auth_mode === 'sso'

  // Conflict detection helpers
  const pinHasBasicAuthConflict = basicAuth?.has_basic_auth === true
  const accessHasBasicAuthConflict = basicAuth?.has_basic_auth === true
  const baConflicts: string[] = []
  if (hasPin) baConflicts.push('an active PIN')
  if ((rules ?? []).length > 0) baConflicts.push(`${(rules ?? []).length} email rule${(rules ?? []).length > 1 ? 's' : ''}`)
  const baHasConflict = baConflicts.length > 0 && !basicAuth?.has_basic_auth

  return (
    <div style={card}>
      {/* Confirmation dialog overlay */}
      {confirmAction && (
        <div style={confirmBox}>
          <span style={{ fontSize: 13, color: 'var(--text)' }}>{confirmAction.message}</span>
          <div style={row}>
            <button style={btn('danger')} onClick={confirmAction.onConfirm}>Confirm</button>
            <button style={btn('ghost')} onClick={() => setConfirmAction(null)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ fontWeight: 700, fontSize: 15, display: 'flex', alignItems: 'center', gap: 6 }}>
            {faviconOk && (
              <img
                src={`./api/tunnels/${tunnel.id}/favicon`}
                alt=""
                width={20}
                height={20}
                style={{ borderRadius: 3, flexShrink: 0 }}
                onError={() => setFaviconOk(false)}
              />
            )}
            {tunnel.name || tunnel.label}
            {tunnel.name && (
              <span style={{ color: 'var(--text-xdim)', fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
                {tunnel.label}
              </span>
            )}
            <span style={{ color: 'var(--text-xdim)', fontWeight: 400, marginLeft: 8, fontSize: 13 }}>
              {isSso ? '🔒 SSO' : '🌐 Open'}
            </span>
          </span>
          <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>{tunnel.service_url}</span>
          {tunnel.state === 'CONNECTING' && (
            <span style={{ color: 'var(--yellow)', fontSize: 12 }}>
              {tunnel.error
                ? `Connection issue: ${tunnel.error}`
                : 'Process running — connecting to relay…'}
            </span>
          )}
          {tunnel.state === 'FAILED' && (
            <span style={{ color: 'var(--red)', fontSize: 12 }}>
              Process exited unexpectedly.{tunnel.error ? ` Last log: ${tunnel.error}` : ' Check Logs for details.'}
            </span>
          )}
          {tunnel.subdomain && !tunnel.public_url && (
            <span style={{ color: 'var(--text-xdim)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
              {tunnel.subdomain}.hle.world
            </span>
          )}
        </div>
        <StatusBadge state={tunnel.state} />
      </div>

      {/* Public URL bar */}
      {tunnel.public_url && tunnel.state === 'CONNECTED' && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 6, padding: '6px 10px',
        }}>
          <a href={tunnel.public_url} target="_blank" rel="noreferrer"
            style={{
              color: 'var(--mint)', fontSize: 13, fontFamily: 'var(--font-mono)',
              flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              textDecoration: 'none',
            }}>
            {tunnel.public_url}
          </a>
          <button
            style={{
              ...btn('ghost'), padding: '3px 10px', fontSize: 11,
              minWidth: 52, textAlign: 'center',
            }}
            onClick={() => {
              navigator.clipboard.writeText(tunnel.public_url!)
              setUrlCopied(true)
              setTimeout(() => setUrlCopied(false), 2000)
            }}
          >
            {urlCopied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      )}

      {/* Action buttons */}
      <div style={row}>
        {tunnel.state === 'CONNECTED' || tunnel.state === 'CONNECTING'
          ? <button style={btn('ghost')} onClick={() => stopTunnel(tunnel.id).then(onRefresh)}>Stop</button>
          : <button style={btn('primary')} onClick={() => startTunnel(tunnel.id).then(onRefresh)}>
              {tunnel.state === 'FAILED' ? 'Retry' : 'Start'}
            </button>
        }
        <button style={btn(panel === 'edit' ? 'active' : 'ghost')} onClick={() => togglePanel('edit')}>
          Edit
        </button>
        {sub && isSso && (
          <button style={btn(panel === 'access' ? 'active' : 'ghost')} onClick={() => togglePanel('access')}>
            Access Rules
          </button>
        )}
        {sub && isSso && (
          <button style={btn(panel === 'pin' ? 'active' : 'ghost')} onClick={() => togglePanel('pin')}>
            PIN
          </button>
        )}
        {sub && (
          <button style={btn(panel === 'basic-auth' ? 'active' : 'ghost')} onClick={() => togglePanel('basic-auth')}>
            Basic Auth
          </button>
        )}
        {sub && (
          <button style={btn(panel === 'share' ? 'active' : 'ghost')} onClick={() => togglePanel('share')}>
            Share
          </button>
        )}
        <button style={btn(panel === 'logs' ? 'active' : 'ghost')} onClick={() => togglePanel('logs')}>
          Logs
        </button>
        <button style={{ ...btn('danger'), marginLeft: 'auto' }}
          onClick={() => removeTunnel(tunnel.id).then(onRefresh)}>
          Remove
        </button>
      </div>

      {error && <p style={{ color: 'var(--red)', fontSize: 13, margin: 0 }}>{error}</p>}

      {/* Edit panel */}
      {panel === 'edit' && (
        <div style={section}>
          <span style={sectionTitle}>Edit Tunnel Settings</span>
          <span style={{ fontSize: 12, color: 'var(--text-xdim)' }}>Saving will restart the tunnel process.</span>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>Service URL</label>
              <input style={inputSm} value={editServiceUrl} onChange={e => setEditServiceUrl(e.target.value)} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>Label (subdomain prefix)</label>
              <input style={inputSm} value={editLabel} onChange={e => setEditLabel(e.target.value.toLowerCase().replace(/[_ .]+/g, '-').replace(/[^a-z0-9-]/g, '').replace(/-{2,}/g, '-'))} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>Display name (optional)</label>
              <input style={inputSm} value={editName} onChange={e => setEditName(e.target.value)} placeholder="e.g. Home Assistant" />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>Auth mode</label>
              <select style={inputSm} value={editAuthMode} onChange={e => setEditAuthMode(e.target.value as 'sso' | 'none')}>
                <option value="sso">SSO (recommended)</option>
                <option value="none">Open (no auth)</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              API key override{' '}
              <span style={{ color: 'var(--text-xdim)', fontWeight: 400 }}>(leave blank to use global key; set to clear override)</span>
            </label>
            <input style={{ ...inputSm, fontFamily: 'var(--font-mono)' }} value={editApiKey}
              onChange={e => setEditApiKey(e.target.value)}
              placeholder="hle_... (optional)" type="password" />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              Upstream basic auth{' '}
              <span style={{ color: 'var(--text-xdim)', fontWeight: 400 }}>(user:pass — injected into requests forwarded to the local service)</span>
            </label>
            <input style={{ ...inputSm, fontFamily: 'var(--font-mono)' }} value={editUpstreamBasicAuth}
              onChange={e => setEditUpstreamBasicAuth(e.target.value)}
              placeholder="username:password (optional)" type="password" />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div>
              <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                Response timeout{' '}
                <span style={{ color: 'var(--text-xdim)', fontWeight: 400 }}>(seconds)</span>
              </label>
              <input style={inputSm} value={editResponseTimeout}
                onChange={e => setEditResponseTimeout(e.target.value.replace(/\D/g, ''))}
                placeholder="30 (default)" type="text" inputMode="numeric" />
            </div>
          </div>

          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', fontSize: 13 }}>
              <input type="checkbox" checked={editVerifySsl} onChange={e => setEditVerifySsl(e.target.checked)} />
              Verify SSL
              <span
                title="Enable only if the service has a valid CA-signed certificate. Self-signed certs will fail."
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 14, height: 14, borderRadius: '50%', background: 'var(--surface)', color: 'var(--text-dim)', fontSize: 10, fontWeight: 700, cursor: 'help' }}
              >?</span>
            </label>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', fontSize: 13 }}>
              <input type="checkbox" checked={editWebsocket} onChange={e => setEditWebsocket(e.target.checked)} />
              Enable WebSocket
              <span
                title="Required for Home Assistant, VS Code Server, and other services that use WebSockets."
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 14, height: 14, borderRadius: '50%', background: 'var(--surface)', color: 'var(--text-dim)', fontSize: 10, fontWeight: 700, cursor: 'help' }}
              >?</span>
            </label>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', fontSize: 13 }}>
              <input type="checkbox" checked={editForwardHost} onChange={e => setEditForwardHost(e.target.checked)} />
              Forward Host header
              <span
                title="Forward the browser's Host header to the local service. Enable for services that validate the Host header (e.g. Home Assistant with external_url)."
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 14, height: 14, borderRadius: '50%', background: 'var(--surface)', color: 'var(--text-dim)', fontSize: 10, fontWeight: 700, cursor: 'help' }}
              >?</span>
            </label>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button style={btn('primary')} onClick={handleSaveEdit} disabled={editSaving || !editServiceUrl || !editLabel}>
              {editSaving ? 'Saving...' : 'Save & Restart'}
            </button>
            <button style={btn('ghost')} onClick={() => setPanel(null)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Access Rules panel */}
      {panel === 'access' && (
        <div style={section}>
          <span style={sectionTitle}>SSO Allow-list</span>
          {!sub
            ? <span style={{ color: 'var(--text-xdim)', fontSize: 13 }}>Tunnel not yet connected — subdomain unknown.</span>
            : <>
              {accessHasBasicAuthConflict && !conflictAcked && (
                <div style={warningBox}>
                  <span>Basic Auth is active — email rules won't be checked until Basic Auth is removed.</span>
                  <div style={{ marginTop: 6 }}>
                    <button style={btn('ghost')} onClick={() => setConflictAcked(true)}>I understand</button>
                  </div>
                </div>
              )}
              {(!accessHasBasicAuthConflict || conflictAcked) && <>
                {(rules ?? []).length === 0 && (
                  <span style={{ color: 'var(--text-xdim)', fontSize: 13 }}>No rules — all SSO users are allowed.</span>
                )}
                {(rules ?? []).map(r => (
                  <div key={r.id} style={{ ...row, justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 13 }}>
                      {r.allowed_email}
                      <span style={{ color: 'var(--text-xdim)', marginLeft: 6 }}>via {r.provider}</span>
                    </span>
                    <button style={{ ...btn('danger'), padding: '2px 8px' }} onClick={() => handleDeleteRule(r.id)}>✕</button>
                  </div>
                ))}
                <div style={row}>
                  <input value={newEmail} onChange={e => setNewEmail(e.target.value)}
                    placeholder="email@example.com" type="email" style={{ ...inputSm, flex: 1 }} />
                  <select value={newProvider} onChange={e => setNewProvider(e.target.value)} style={inputSm}>
                    {['any', 'google', 'github', 'hle'].map(p => <option key={p}>{p}</option>)}
                  </select>
                  <button style={btn('primary')} onClick={handleAddRule} disabled={!newEmail || !/\S+@\S+\.\S+/.test(newEmail)}>Add</button>
                </div>
              </>}
            </>
          }
        </div>
      )}

      {/* PIN panel */}
      {panel === 'pin' && (
        <div style={section}>
          <span style={sectionTitle}>PIN Protection</span>
          {!sub
            ? <span style={{ color: 'var(--text-xdim)', fontSize: 13 }}>Tunnel not yet connected — subdomain unknown.</span>
            : <>
              <span style={{ fontSize: 13, color: hasPin ? 'var(--green)' : 'var(--text-xdim)' }}>
                {hasPin ? '🔐 PIN is set' : 'No PIN — visitors only need SSO login'}
              </span>

              {pinHasBasicAuthConflict && !hasPin && !conflictAcked && (
                <div style={warningBox}>
                  <span>Basic Auth is active — this PIN won't be checked until Basic Auth is removed.</span>
                  <div style={{ marginTop: 6 }}>
                    <button style={btn('ghost')} onClick={() => setConflictAcked(true)}>I understand</button>
                  </div>
                </div>
              )}

              {(!pinHasBasicAuthConflict || hasPin || conflictAcked) && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={row}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <input value={newPin} onChange={e => setNewPin(e.target.value.replace(/\D/g, '').slice(0, 8))}
                        placeholder="4-8 digits" type="password" maxLength={8}
                        style={pinTouched && !pinValid ? inputErr : { ...inputSm, width: 120 }} />
                      {pinTouched && !pinValid && (
                        <span style={{ fontSize: 11, color: 'var(--red)' }}>Must be 4-8 digits</span>
                      )}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <input value={confirmPin} onChange={e => setConfirmPin(e.target.value.replace(/\D/g, '').slice(0, 8))}
                        placeholder="Confirm PIN" type="password" maxLength={8}
                        style={confirmPinTouched && !pinMatch ? inputErr : { ...inputSm, width: 120 }} />
                      {confirmPinTouched && !pinMatch && (
                        <span style={{ fontSize: 11, color: 'var(--red)' }}>PINs don't match</span>
                      )}
                    </div>
                    <button style={btn('primary')} onClick={handleSetPin} disabled={!pinValid || !pinMatch}>
                      {hasPin ? 'Update PIN' : 'Set PIN'}
                    </button>
                  </div>
                  {hasPin && <button style={{ ...btn('danger'), alignSelf: 'flex-start' }} onClick={handleRemovePin}>Remove PIN</button>}
                </div>
              )}
            </>
          }
        </div>
      )}

      {/* Basic Auth panel */}
      {panel === 'basic-auth' && (
        <div style={section}>
          <span style={sectionTitle}>Basic Auth</span>
          <span style={{ fontSize: 12, color: 'var(--text-xdim)' }}>
            Require HTTP Basic Auth credentials to access this tunnel URL.
          </span>
          {!sub
            ? <span style={{ color: 'var(--text-xdim)', fontSize: 13 }}>Tunnel not yet connected — subdomain unknown.</span>
            : <>
              <span style={{ fontSize: 13, color: basicAuth?.has_basic_auth ? 'var(--green)' : 'var(--text-xdim)' }}>
                {basicAuth?.has_basic_auth
                  ? `Enabled (user: ${basicAuth.username})`
                  : 'Not configured'}
              </span>

              {baHasConflict && !conflictAcked && (
                <div style={warningBox}>
                  <span>This tunnel has {baConflicts.join(' and ')} — enabling Basic Auth will bypass them.</span>
                  <div style={{ marginTop: 6 }}>
                    <button style={btn('ghost')} onClick={() => setConflictAcked(true)}>I understand</button>
                  </div>
                </div>
              )}

              {(!baHasConflict || conflictAcked || basicAuth?.has_basic_auth) && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <input value={baUsername} onChange={e => setBaUsername(e.target.value)}
                        placeholder="username" autoComplete="off"
                        style={baUsernameTouched && !baUsernameValid ? inputErr : { ...inputSm }} />
                      {baUsernameTouched && !baUsernameValid && (
                        <span style={{ fontSize: 11, color: 'var(--red)' }}>
                          {baUsername.includes(':') ? 'Must not contain ":"' : 'Required'}
                        </span>
                      )}
                    </div>
                    <div />
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <input value={baPassword} onChange={e => setBaPassword(e.target.value)}
                        placeholder="password (min 8 chars)" type="password" autoComplete="new-password"
                        style={baPasswordTouched && !baPasswordValid ? inputErr : { ...inputSm }} />
                      {baPasswordTouched && !baPasswordValid && (
                        <span style={{ fontSize: 11, color: 'var(--red)' }}>Minimum 8 characters</span>
                      )}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <input value={baConfirmPassword} onChange={e => setBaConfirmPassword(e.target.value)}
                        placeholder="confirm password" type="password" autoComplete="new-password"
                        style={baConfirmTouched && !baPasswordMatch ? inputErr : { ...inputSm }} />
                      {baConfirmTouched && !baPasswordMatch && (
                        <span style={{ fontSize: 11, color: 'var(--red)' }}>Passwords don't match</span>
                      )}
                    </div>
                  </div>
                  <div style={row}>
                    <button style={btn('primary')} onClick={handleSetBasicAuth}
                      disabled={!baUsernameValid || !baPasswordValid || !baPasswordMatch}>
                      {basicAuth?.has_basic_auth ? 'Update' : 'Set'}
                    </button>
                    {basicAuth?.has_basic_auth && (
                      <button style={btn('danger')} onClick={handleRemoveBasicAuth}>Remove</button>
                    )}
                  </div>
                </div>
              )}
            </>
          }
        </div>
      )}

      {/* Share Links panel */}
      {panel === 'share' && (
        <div style={section}>
          <span style={sectionTitle}>Share Links</span>
          {!sub
            ? <span style={{ color: 'var(--text-xdim)', fontSize: 13 }}>Tunnel not yet connected — subdomain unknown.</span>
            : <>
              {newShareUrl && (
                <div style={{ background: 'var(--green-tint-bg)', border: '1px solid var(--green-tint-border)', borderRadius: 6, padding: '8px 12px' }}>
                  <span style={{ fontSize: 12, color: 'var(--green)', display: 'block', marginBottom: 4 }}>Link created:</span>
                  <a href={newShareUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--mint)', fontSize: 13, wordBreak: 'break-all' }}>{newShareUrl}</a>
                </div>
              )}
              <div style={row}>
                <input value={shareLabel} onChange={e => setShareLabel(e.target.value)}
                  placeholder="Label (optional)" style={{ ...inputSm, flex: 1 }} />
                <select value={shareDuration} onChange={e => setShareDuration(e.target.value as '1h' | '24h' | '7d')} style={inputSm}>
                  {['1h', '24h', '7d'].map(d => <option key={d}>{d}</option>)}
                </select>
                <button style={btn('primary')} onClick={handleCreateShare}>Create</button>
              </div>
              {(shareLinks ?? []).length === 0
                ? <span style={{ color: 'var(--text-xdim)', fontSize: 13 }}>No active share links.</span>
                : (shareLinks ?? []).map(l => (
                  <div key={l.id} style={{ ...row, justifyContent: 'space-between', fontSize: 13 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={{ color: l.is_active ? 'var(--text)' : 'var(--text-xdim)' }}>
                        {l.label || `Link #${l.id}`}
                        <span style={{ color: 'var(--text-xdim)', marginLeft: 8 }}>expires {new Date(l.expires_at).toLocaleDateString()}</span>
                        {l.max_uses && <span style={{ color: 'var(--text-xdim)', marginLeft: 8 }}>{l.use_count}/{l.max_uses} uses</span>}
                      </span>
                    </div>
                    <button style={{ ...btn('danger'), padding: '2px 8px' }} onClick={() => handleDeleteShare(l.id)}>✕</button>
                  </div>
                ))
              }
            </>
          }
        </div>
      )}

      {/* Logs panel */}
      {panel === 'logs' && (
        <div style={section}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={sectionTitle}>Tunnel Logs <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-xdim)' }}>(auto-refreshing)</span></span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                style={{ ...btn(autoScroll ? 'active' : 'ghost'), fontSize: 11 }}
                onClick={() => {
                  const next = !autoScroll
                  setAutoScroll(next)
                  if (next && logsRef.current) {
                    logsRef.current.scrollTop = logsRef.current.scrollHeight
                  }
                }}
              >
                {autoScroll ? 'Auto-scroll: On' : 'Auto-scroll: Off'}
              </button>
              <a
                href={`./api/tunnels/${tunnel.id}/logs/download`}
                download={`tunnel-${tunnel.id}.log`}
                style={{ ...btn('ghost'), fontSize: 11, textDecoration: 'none', display: 'inline-block' }}
              >
                Download
              </a>
              <button style={{ ...btn('ghost'), fontSize: 11 }}
                onClick={async () => setLogs((await getTunnelLogs(tunnel.id)).lines)}>
                Refresh
              </button>
            </div>
          </div>
          <pre ref={logsRef} onScroll={handleLogsScroll} style={{
            background: 'var(--surface)', borderRadius: 6, padding: '10px 12px',
            fontSize: 11, color: 'var(--text-dim)', overflowX: 'auto', maxHeight: 280,
            overflowY: 'auto', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            fontFamily: 'var(--font-mono)',
          }}>
            {(logs ?? []).length === 0
              ? 'No log output yet.'
              : (logs ?? []).join('\n')}
          </pre>
        </div>
      )}
    </div>
  )
}
