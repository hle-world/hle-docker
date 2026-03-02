import { useEffect, useState, useCallback } from 'react'
import type { TunnelStatus } from './api/client'
import {
  getConfig, updateConfig,
  getTunnels,
} from './api/client'
import { TunnelCard } from './components/TunnelCard'
import { AddTunnelModal } from './components/AddTunnelModal'

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------
const colors = {
  bg: '#111318', surface: '#1e2128', border: '#2d3139',
  text: '#e0e0e0', muted: '#9ca3af', faint: '#6b7280',
  blue: '#3b82f6', blueDark: '#1d4ed8',
  green: '#4ade80', yellow: '#facc15', red: '#f87171',
  amber: '#fbbf24',
}

const inputStyle: React.CSSProperties = {
  padding: '8px 12px', borderRadius: 7, border: `1px solid ${colors.border}`,
  background: colors.surface, color: colors.text, fontSize: 14, width: '100%',
  boxSizing: 'border-box',
}
const btnPrimary: React.CSSProperties = {
  padding: '8px 18px', borderRadius: 7, border: 'none', cursor: 'pointer',
  background: colors.blue, color: '#fff', fontSize: 13, fontWeight: 600,
}
const btnDisabled: React.CSSProperties = {
  ...btnPrimary, background: colors.surface, color: colors.faint, cursor: 'not-allowed',
}

// ---------------------------------------------------------------------------
// Collapsible section
// ---------------------------------------------------------------------------
function Section({
  title, open, onToggle, badge, children,
}: {
  title: string
  open: boolean
  onToggle: () => void
  badge?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div style={{ border: `1px solid ${colors.border}`, borderRadius: 10, overflow: 'hidden' }}>
      <button
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 20px', background: colors.surface, border: 'none', cursor: 'pointer',
          color: colors.text, fontSize: 15, fontWeight: 700, textAlign: 'left',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            fontSize: 11, color: colors.muted, transform: open ? 'rotate(90deg)' : 'none',
            display: 'inline-block', transition: 'transform 0.15s',
          }}>▶</span>
          {title}
          {badge}
        </span>
      </button>
      {open && (
        <div style={{ padding: '0 20px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {children}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Settings section content
// ---------------------------------------------------------------------------
function SettingsContent({
  apiKeySet, onSaved,
}: {
  apiKeySet: boolean
  onSaved: () => void
}) {
  const [apiKey, setApiKey] = useState('')
  const [masked, setMasked] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getConfig().then(cfg => setMasked(cfg.api_key_masked)).catch(() => null)
  }, [apiKeySet])

  async function saveKey() {
    if (!apiKey) return
    setSaving(true); setError(''); setSaved(false)
    try {
      await updateConfig(apiKey)
      setSaved(true); setApiKey('')
      const cfg = await getConfig()
      setMasked(cfg.api_key_masked)
      onSaved()
    } catch (e) { setError(String(e)) }
    finally { setSaving(false) }
  }

  return (
    <>
      {/* API key */}
      <div style={{ marginTop: 4 }}>
        <div style={{ fontSize: 13, color: colors.muted, fontWeight: 500, marginBottom: 6 }}>API Key</div>
        {masked && (
          <p style={{ fontSize: 13, color: colors.faint, margin: '0 0 8px' }}>
            Current: <code style={{ color: colors.muted }}>{masked}</code>
          </p>
        )}
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && saveKey()}
            placeholder="hle_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
          />
          <button
            style={apiKey && !saving ? btnPrimary : btnDisabled}
            onClick={saveKey}
            disabled={!apiKey || saving}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
        {error && <p style={{ color: colors.red, fontSize: 13, margin: '8px 0 0' }}>{error}</p>}
        {saved && <p style={{ color: colors.green, fontSize: 13, margin: '8px 0 0' }}>✓ Saved — tunnels will start automatically.</p>}
        <p style={{ fontSize: 12, color: colors.faint, margin: '8px 0 0' }}>
          New user?{' '}
          <a href="https://hle.world/register" target="_blank" rel="noreferrer" style={{ color: colors.blue }}>
            Create a free account
          </a>
          {' '}· API key at{' '}
          <a href="https://hle.world/dashboard" target="_blank" rel="noreferrer" style={{ color: colors.blue }}>
            hle.world/dashboard
          </a>
        </p>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Documentation section content
// ---------------------------------------------------------------------------
function DocsContent() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 4 }}>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: colors.text }}>SSO vs Open tunnels</div>
        <p style={{ fontSize: 13, color: colors.muted, margin: 0, lineHeight: 1.6 }}>
          <strong style={{ color: colors.text }}>SSO</strong> — visitors must log in via Google or GitHub
          before accessing your service. You can restrict access to specific email addresses using
          Access Rules.
        </p>
        <p style={{ fontSize: 13, color: colors.muted, margin: 0, lineHeight: 1.6 }}>
          <strong style={{ color: colors.text }}>Open</strong> — no authentication. The service is
          publicly accessible via the tunnel URL. Use this for services with their own auth.
        </p>
      </div>

      <div style={{ borderTop: `1px solid ${colors.border}` }} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: colors.text }}>Self-signed certificates</div>
        <p style={{ fontSize: 13, color: colors.muted, margin: 0, lineHeight: 1.6 }}>
          If your local service uses HTTPS with a self-signed certificate (e.g. a NAS or router),
          enable <strong style={{ color: colors.text }}>Skip SSL verification</strong> when adding the tunnel.
          The tunnel URL itself is always secured with a valid certificate.
        </p>
      </div>

    </div>
  )
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------
export default function App() {
  const [apiKeySet, setApiKeySet] = useState<boolean | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [tunnelsOpen, setTunnelsOpen] = useState(true)
  const [docsOpen, setDocsOpen] = useState(false)

  const [tunnels, setTunnels] = useState<TunnelStatus[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [loadError, setLoadError] = useState('')

  // Load config to determine if key is set
  useEffect(() => {
    getConfig().then(cfg => {
      setApiKeySet(cfg.api_key_set)
      // Auto-open settings if no API key
      if (!cfg.api_key_set) setSettingsOpen(true)
    }).catch(() => { setApiKeySet(false); setSettingsOpen(true) })
  }, [])

  const loadTunnels = useCallback(async () => {
    try { setTunnels(await getTunnels()) }
    catch (e) { setLoadError(String(e)) }
  }, [])

  useEffect(() => {
    loadTunnels()
    const id = setInterval(loadTunnels, 5000)
    return () => clearInterval(id)
  }, [loadTunnels])

  function handleKeySaved() {
    setApiKeySet(true)
    setSettingsOpen(false)
    loadTunnels()
  }

  const noKey = apiKeySet === false

  return (
    <div style={{ minHeight: '100vh', background: colors.bg, color: colors.text, fontFamily: 'system-ui, sans-serif' }}>
      {/* Header */}
      <header style={{
        padding: '16px 24px', background: '#161820',
        borderBottom: `1px solid ${colors.border}`,
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span style={{ fontSize: 20 }}>🌐</span>
        <span style={{ fontWeight: 700, fontSize: 17, letterSpacing: '-0.3px' }}>
          Home Lab Everywhere
        </span>
      </header>

      <main style={{ padding: '20px 24px', maxWidth: 720, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 12 }}>

        {/* Settings section */}
        <Section
          title="Settings"
          open={settingsOpen}
          onToggle={() => setSettingsOpen(o => !o)}
          badge={noKey ? (
            <span style={{
              fontSize: 11, background: '#92400e', color: colors.amber,
              borderRadius: 4, padding: '1px 7px', fontWeight: 600,
            }}>API key required</span>
          ) : undefined}
        >
          {apiKeySet !== null && (
            <SettingsContent
              apiKeySet={apiKeySet}
              onSaved={handleKeySaved}
            />
          )}
        </Section>

        {/* Tunnels section */}
        <Section
          title="Tunnels"
          open={tunnelsOpen}
          onToggle={() => setTunnelsOpen(o => !o)}
          badge={tunnels.length > 0 ? (
            <span style={{
              fontSize: 11, background: colors.surface, color: colors.faint,
              border: `1px solid ${colors.border}`, borderRadius: 10, padding: '1px 8px',
            }}>{tunnels.length}</span>
          ) : undefined}
        >
          {/* Add tunnel button + no-key warning */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 }}>
            <span style={{ fontSize: 13, color: colors.faint }}>
              {tunnels.length === 0 ? 'No tunnels yet.' : ''}
            </span>
            <button
              style={noKey ? btnDisabled : btnPrimary}
              onClick={() => !noKey && setShowAdd(true)}
              title={noKey ? 'Set your API key in Settings first' : undefined}
            >
              + Add Tunnel
            </button>
          </div>

          {noKey && (
            <div style={{
              background: '#422006', border: `1px solid #92400e`,
              borderRadius: 8, padding: '10px 14px', fontSize: 13, color: colors.amber, lineHeight: 1.6,
            }}>
              No API key configured.{' '}
              <button
                onClick={() => setSettingsOpen(true)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: colors.amber, fontWeight: 700, textDecoration: 'underline', fontSize: 13, padding: 0 }}
              >
                Open Settings
              </button>
              {' '}to add your key.
            </div>
          )}

          {loadError && <p style={{ color: colors.red, fontSize: 13 }}>{loadError}</p>}

          {tunnels.map(t => (
            <TunnelCard key={t.id} tunnel={t} onRefresh={loadTunnels} />
          ))}

          {/* Documentation sub-section */}
          <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: 12 }}>
            <Section
              title="Documentation"
              open={docsOpen}
              onToggle={() => setDocsOpen(o => !o)}
            >
              <DocsContent />
            </Section>
          </div>
        </Section>

      </main>

      {showAdd && (
        <AddTunnelModal
          onClose={() => setShowAdd(false)}
          onAdded={() => { setShowAdd(false); loadTunnels() }}
        />
      )}
    </div>
  )
}
