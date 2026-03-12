import { useState } from 'react'
import { addTunnel } from '../api/client'

interface Props {
  onClose: () => void
  onAdded: () => void
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'var(--overlay)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
}
const modal: React.CSSProperties = {
  background: 'var(--bg-raised)', border: '1px solid var(--border)', borderRadius: 12,
  padding: 28, width: 420, display: 'flex', flexDirection: 'column', gap: 16,
}
const fieldStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 6 }
const labelStyle: React.CSSProperties = { fontSize: 13, color: 'var(--text-dim)', fontWeight: 500 }
const inputStyle: React.CSSProperties = {
  padding: '7px 12px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'var(--bg)', color: 'var(--text)', fontSize: 14, fontFamily: 'inherit',
}
const btn = (primary: boolean): React.CSSProperties => ({
  padding: '8px 18px', borderRadius: 6, border: 'none', cursor: 'pointer',
  background: primary ? 'var(--mint)' : 'var(--surface)', color: primary ? 'var(--bg)' : 'var(--text-dim)',
  fontSize: 14, fontWeight: 500, fontFamily: 'inherit',
})

export function AddTunnelModal({ onClose, onAdded }: Props) {
  const [serviceUrl, setServiceUrl] = useState('')
  const [label, setLabel] = useState('')
  const [name, setName] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [verifySsl, setVerifySsl] = useState(false)
  const [websocket, setWebsocket] = useState(true)
  const [apiKeyOverride, setApiKeyOverride] = useState('')
  const [upstreamBasicAuth, setUpstreamBasicAuth] = useState('')
  const [forwardHost, setForwardHost] = useState(false)
  const [responseTimeout, setResponseTimeout] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit() {
    setLoading(true)
    setError('')
    try {
      await addTunnel({
        service_url: serviceUrl,
        label,
        name: name || undefined,
        auth_mode: 'sso',
        verify_ssl: verifySsl,
        websocket_enabled: websocket,
        api_key: apiKeyOverride || undefined,
        upstream_basic_auth: upstreamBasicAuth || undefined,
        forward_host: forwardHost || undefined,
        response_timeout: responseTimeout ? parseInt(responseTimeout, 10) : undefined,
      })
      onAdded()
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={modal}>
        <h2 style={{ fontSize: 17, fontWeight: 700, fontFamily: 'var(--font-display)' }}>Add Tunnel</h2>

        <div style={fieldStyle}>
          <label style={labelStyle}>Service URL</label>
          <input style={inputStyle} value={serviceUrl} onChange={e => setServiceUrl(e.target.value)}
            placeholder="http://192.168.1.50:8096" />
        </div>

        <div style={fieldStyle}>
          <label style={labelStyle}>Name <span style={{ color: 'var(--text-xdim)', fontWeight: 400 }}>(display only, optional)</span></label>
          <input style={inputStyle} value={name} onChange={e => setName(e.target.value)}
            placeholder="e.g. Proxmox, Jellyfin, Home Assistant" />
        </div>

        <div style={fieldStyle}>
          <label style={labelStyle}>Label <span style={{ color: 'var(--text-xdim)', fontWeight: 400 }}>(used in subdomain)</span></label>
          <input style={inputStyle} value={label}
            onChange={e => setLabel(e.target.value.toLowerCase().replace(/[_ .]+/g, '-').replace(/[^a-z0-9-]/g, '').replace(/-{2,}/g, '-'))}
            placeholder="jellyfin" />
          <span style={{ fontSize: 12, color: 'var(--text-xdim)' }}>
            Subdomain: <code style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>{label || 'label'}-<span style={{ opacity: 0.5 }}>xxx</span>.hle.world</code>
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-xdim)' }}>
            Lowercase letters, numbers, and hyphens only. Your unique code is appended automatically.
          </span>
        </div>

        {/* Advanced toggle */}
        <button
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-xdim)', fontSize: 13, textAlign: 'left', padding: 0, fontFamily: 'inherit' }}
          onClick={() => setShowAdvanced(v => !v)}
        >
          {showAdvanced ? '▾' : '▸'} Advanced options
        </button>

        {showAdvanced && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingLeft: 12, borderLeft: '2px solid var(--border)' }}>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', fontSize: 14 }}>
              <input type="checkbox" checked={verifySsl} onChange={e => setVerifySsl(e.target.checked)} />
              <span>Verify SSL certificate</span>
              <span
                title="By default, SSL verification is disabled so self-signed certificates (common on Proxmox, Unraid, TrueNAS, etc.) work without extra setup. Enable this only if your service has a valid certificate from a trusted CA."
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, borderRadius: '50%', background: 'var(--surface)', color: 'var(--text-dim)', fontSize: 11, fontWeight: 700, cursor: 'help', userSelect: 'none' }}
              >?</span>
            </label>

            <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', fontSize: 14 }}>
              <input type="checkbox" checked={websocket} onChange={e => setWebsocket(e.target.checked)} />
              <span>Enable WebSocket support</span>
              <span
                title="Required for services that use WebSockets (Home Assistant, VS Code Server, etc.). Disable only if the service does not support them and you're seeing connection issues."
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, borderRadius: '50%', background: 'var(--surface)', color: 'var(--text-dim)', fontSize: 11, fontWeight: 700, cursor: 'help', userSelect: 'none' }}
              >?</span>
            </label>

            <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', fontSize: 14 }}>
              <input type="checkbox" checked={forwardHost} onChange={e => setForwardHost(e.target.checked)} />
              <span>Forward Host header</span>
              <span
                title="Forward the browser's Host header to the local service. Enable for services like Home Assistant that validate the Host header against their external_url. By default, the Host header is set from the target URL to avoid 502 errors behind reverse proxies."
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, borderRadius: '50%', background: 'var(--surface)', color: 'var(--text-dim)', fontSize: 11, fontWeight: 700, cursor: 'help', userSelect: 'none' }}
              >?</span>
            </label>

            <div style={fieldStyle}>
              <label style={{ ...labelStyle, fontSize: 12 }}>
                API key override <span style={{ color: 'var(--text-xdim)', fontWeight: 400 }}>(optional — uses global key if blank)</span>
              </label>
              <input style={{ ...inputStyle, fontSize: 13 }} value={apiKeyOverride}
                onChange={e => setApiKeyOverride(e.target.value)}
                placeholder="hle_..." type="password" />
            </div>

            <div style={fieldStyle}>
              <label style={{ ...labelStyle, fontSize: 12 }}>
                Upstream basic auth <span style={{ color: 'var(--text-xdim)', fontWeight: 400 }}>(optional — user:pass injected into forwarded requests)</span>
              </label>
              <input style={{ ...inputStyle, fontSize: 13 }} value={upstreamBasicAuth}
                onChange={e => setUpstreamBasicAuth(e.target.value)}
                placeholder="username:password" type="password" />
            </div>

            <div style={fieldStyle}>
              <label style={{ ...labelStyle, fontSize: 12 }}>
                Response timeout{' '}
                <span style={{ color: 'var(--text-xdim)', fontWeight: 400 }}>(seconds — default: 30, max: 1200)</span>
              </label>
              <input style={{ ...inputStyle, fontSize: 13 }} value={responseTimeout}
                onChange={e => setResponseTimeout(e.target.value.replace(/\D/g, ''))}
                placeholder="30" type="text" inputMode="numeric" />
              <span style={{ fontSize: 11, color: 'var(--text-xdim)' }}>
                Increase for services that do heavy processing or trigger long pipelines.
              </span>
            </div>
          </div>
        )}

        {error && <p style={{ color: 'var(--red)', fontSize: 13 }}>{error}</p>}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button style={btn(false)} onClick={onClose}>Cancel</button>
          <button style={btn(true)} onClick={submit} disabled={loading || !serviceUrl || !label}>
            {loading ? 'Adding...' : 'Add Tunnel'}
          </button>
        </div>
      </div>
    </div>
  )
}
