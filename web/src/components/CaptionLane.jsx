export function CaptionLane({ segments, className = "" }) {
  return (
    <ol className={`caption-lane ${className}`.trim()}>
      {segments.map((seg) => (
        <li
          key={seg.uid ?? `${seg.t0_ms}-${seg.t1_ms}-${seg.state}`}
          className="cue"
          data-state={seg.state}
          data-t0={seg.t0_ms}
          data-t1={seg.t1_ms}
          data-session-id={seg.session_id || undefined}
          data-clause-id={seg.clause_id || undefined}
          data-lang={seg.lang || undefined}
          data-provider={seg.provider || undefined}
          data-audio-end-wall-ms={seg.audio_end_wall_ms ?? undefined}
        >
          {seg.text}
        </li>
      ))}
    </ol>
  );
}
