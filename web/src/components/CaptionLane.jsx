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
        >
          {seg.text}
        </li>
      ))}
    </ol>
  );
}
