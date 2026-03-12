type State = 'CONNECTED' | 'CONNECTING' | 'STOPPED' | 'FAILED'

const config: Record<State, { color: string; label: string; pulse: boolean }> = {
  CONNECTED:  { color: 'var(--green)', label: 'Connected',  pulse: false },
  CONNECTING: { color: 'var(--yellow)', label: 'Connecting', pulse: true  },
  STOPPED:    { color: 'var(--text-xdim)', label: 'Stopped',    pulse: false },
  FAILED:     { color: 'var(--red)', label: 'Failed',     pulse: false },
}

export function StatusBadge({ state }: { state: string }) {
  const { color, label, pulse } = config[state as State] ?? config.STOPPED

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0,
        boxShadow: state === 'CONNECTED' ? '0 0 6px var(--green)' : 'none',
        animation: pulse ? 'hle-pulse 1.2s ease-in-out infinite' : 'none',
      }} />
      {label}
    </span>
  )
}
