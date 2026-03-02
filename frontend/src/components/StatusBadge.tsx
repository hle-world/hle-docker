type State = 'CONNECTED' | 'CONNECTING' | 'STOPPED' | 'FAILED'

const config: Record<State, { color: string; label: string; pulse: boolean }> = {
  CONNECTED:  { color: '#4ade80', label: 'Connected',  pulse: false },
  CONNECTING: { color: '#facc15', label: 'Connecting', pulse: true  },
  STOPPED:    { color: '#6b7280', label: 'Stopped',    pulse: false },
  FAILED:     { color: '#f87171', label: 'Failed',     pulse: false },
}

export function StatusBadge({ state }: { state: string }) {
  const { color, label, pulse } = config[state as State] ?? config.STOPPED

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0,
        boxShadow: state === 'CONNECTED' ? `0 0 6px ${color}` : 'none',
        animation: pulse ? 'hle-pulse 1.2s ease-in-out infinite' : 'none',
      }} />
      <style>{`
        @keyframes hle-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.4; transform: scale(0.75); }
        }
      `}</style>
      {label}
    </span>
  )
}
