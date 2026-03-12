/** Network Globe — Globe with meridian lines, two connected nodes,
 *  broadcast pulses, and animated data stream representing live
 *  "everywhere" connectivity. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <style>{`
        @keyframes hle-stream {
          0%   { offset-distance: 0%;   opacity: 0; }
          5%   { opacity: 1; }
          90%  { opacity: 1; }
          100% { offset-distance: 100%; opacity: 0; }
        }
      `}</style>
      {/* Globe outer circle */}
      <circle cx="16" cy="16" r="13" stroke="currentColor" strokeWidth="1.5" opacity="0.5" />
      {/* Vertical meridian */}
      <ellipse cx="16" cy="16" rx="6" ry="13" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      {/* Horizontal equator */}
      <ellipse cx="16" cy="16" rx="13" ry="4" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      {/* Home node — bottom left */}
      <circle cx="9" cy="20" r="2.5" fill="currentColor" opacity="0.9" />
      {/* Connection line — home to relay */}
      <line x1="11" y1="19" x2="20" y2="12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity="0.7" />
      {/* Relay node — top right */}
      <circle cx="21" cy="11" r="2" fill="currentColor" opacity="0.6" />
      {/* Broadcast pulse from relay */}
      <circle cx="21" cy="11" r="4" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      <circle cx="21" cy="11" r="6.5" stroke="currentColor" strokeWidth="0.8" opacity="0.15" />
      {/* Data stream particles */}
      <circle
        r="1"
        fill="#ffd866"
        opacity="0"
        style={{
          offsetPath: "path('M21,11 L9,20')",
          animation: "hle-stream 1.6s ease-in-out infinite",
          filter: "drop-shadow(0 0 2px #ffd866)",
        }}
      />
      <circle
        r="0.8"
        fill="#ffd866"
        opacity="0"
        style={{
          offsetPath: "path('M21,11 L9,20')",
          animation: "hle-stream 1.6s ease-in-out 0.5s infinite",
        }}
      />
    </svg>
  );
}
