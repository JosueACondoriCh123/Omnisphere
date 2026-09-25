export function playMockCaptions(stageId, lang, onMessage) {
  const base = 842300;
  const original = "the system knows what the talk is about before the speaker opens their mouth";
  const drafts = [
    { at: 180, t1: 842900, text: "el sistema sabe" },
    { at: 480, t1: 843050, text: "el sistema sabe de qué charla se trata" },
  ];
  const timers = [];

  for (const draft of drafts) {
    timers.push(
      setTimeout(() => {
        onMessage({
          type: "caption",
          stage_id: String(stageId),
          t0_ms: base,
          t1_ms: draft.t1,
          state: "draft",
          revision: 1,
          tier: 1,
          lang,
          text: lang === "en" ? original.split(" ").slice(0, 6).join(" ") : draft.text,
          original,
          emitted_at_ms: draft.t1,
          traces: [
            { hop: "ingest", t_wall_ms: base },
            { hop: "vad", t_wall_ms: base + 40 },
            { hop: "tier1", t_wall_ms: base + 280 },
          ],
        });
      }, draft.at),
    );
  }

  timers.push(
    setTimeout(() => {
      onMessage({
        type: "caption",
        stage_id: String(stageId),
        t0_ms: base,
        t1_ms: 843100,
        state: "committed",
        revision: 2,
        tier: 2,
        lang,
        text:
          lang === "en"
            ? original
            : "El sistema sabe de qué charla se trata antes de que el orador abra la boca.",
        original,
        emitted_at_ms: 843420,
        traces: [
          { hop: "ingest", t_wall_ms: 843000 },
          { hop: "vad", t_wall_ms: 843040 },
          { hop: "tier1", t_wall_ms: 843180 },
          { hop: "tier2a", t_wall_ms: 843260 },
          { hop: "tier2b", t_wall_ms: 843340 },
          { hop: "reconciler", t_wall_ms: 843380 },
          { hop: "fanout", t_wall_ms: 843400 },
        ],
      });
    }, 3000),
  );

  return () => {
    for (const timer of timers) clearTimeout(timer);
  };
}
