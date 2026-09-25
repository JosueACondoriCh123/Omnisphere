/** Client reconciler. Port of carril2/reconciler.py — timestamps only, never text. */

function overlaps(a, b) {
  return a.t0_ms < b.t1_ms && b.t0_ms < a.t1_ms;
}

function sortWindow(a, b) {
  return a.t0_ms - b.t0_ms || a.t1_ms - b.t1_ms;
}

function toSegment(ev, uid) {
  return {
    uid,
    session_id: ev.session_id ?? null,
    clause_id: ev.clause_id ?? null,
    provider: ev.provider ?? null,
    t0_ms: ev.t0_ms,
    t1_ms: ev.t1_ms,
    text: ev.text ?? "",
    original: ev.original ?? "",
    state: ev.state,
    revision: ev.revision ?? 0,
    tier: ev.tier ?? 0,
    lang: ev.lang ?? "es",
    traces: ev.traces ?? [],
    emitted_at_ms: ev.emitted_at_ms ?? 0,
    audio_end_wall_ms: ev.audio_end_wall_ms ?? null,
  };
}

export class Reconciler {
  constructor(stageId, maxPendingDrafts = 64) {
    this.stageId = stageId;
    this._maxDrafts = maxPendingDrafts;
    this._committed = [];
    this._drafts = [];
    this._watermarkMs = 0;
    this._nextUid = 1;
    this._sessionId = null;
    this._commitKeys = new Set();
    this.rejected = {};
  }

  get watermarkMs() {
    return this._watermarkMs;
  }

  view() {
    return [...this._committed, ...this._drafts].sort(sortWindow);
  }

  committed() {
    return [...this._committed];
  }

  dropDrafts() {
    this._drafts = [];
  }

  setSession(sessionId) {
    if (sessionId == null || sessionId === this._sessionId) return;
    this._sessionId = sessionId;
    this._committed = [];
    this._drafts = [];
    this._commitKeys.clear();
    this._watermarkMs = 0;
  }

  apply(ev) {
    if (ev.stage_id != null && String(ev.stage_id) !== String(this.stageId)) {
      return { accepted: false, reason: "wrong_stage" };
    }
    if (ev.session_id) {
      if (this._sessionId && ev.session_id !== this._sessionId) {
        return this._reject("wrong_session");
      }
      this.setSession(ev.session_id);
    }
    if (ev.state === "committed") {
      return this._applyCommit(ev);
    }
    return this._applyDraft(ev);
  }

  _reject(reason) {
    this.rejected[reason] = (this.rejected[reason] ?? 0) + 1;
    return { accepted: false, reason };
  }

  _takeUid(dropped) {
    return dropped[0]?.uid ?? this._nextUid++;
  }

  _applyDraft(ev) {
    if (ev.t1_ms <= this._watermarkMs) {
      return this._reject("stale_draft");
    }
    const dropped = this._drafts.filter((d) => overlaps(d, ev));
    this._drafts = this._drafts.filter((d) => !overlaps(d, ev));
    this._drafts.push(toSegment(ev, this._takeUid(dropped)));
    this._drafts.sort(sortWindow);
    if (this._drafts.length > this._maxDrafts) {
      this._drafts = this._drafts.slice(-this._maxDrafts);
    }
    return { accepted: true, dropped_drafts: dropped.length };
  }

  _applyCommit(ev) {
    const key = ev.session_id && ev.clause_id
      ? `${ev.session_id}:${ev.clause_id}:${ev.lang ?? "es"}` : null;
    const oldWatermark = this._watermarkMs;
    const dropped = this._drafts.filter((draft) => overlaps(draft, ev));
    this._drafts = this._drafts.filter((draft) => !overlaps(draft, ev));
    if (key && this._commitKeys.has(key)) return this._reject("duplicate_commit");

    for (let i = 0; i < this._committed.length; i += 1) {
      const seg = this._committed[i];
      if (!overlaps(seg, ev)) continue;
      if (seg.t0_ms === ev.t0_ms && seg.t1_ms === ev.t1_ms) {
        this._watermarkMs = Math.max(this._watermarkMs, ev.t1_ms);
        this._drafts = this._drafts.filter(
          (draft) => draft.t1_ms > this._watermarkMs,
        );
        return this._reject("duplicate_commit");
      }
      return this._reject("frozen_region");
    }

    this._committed.push(toSegment(ev, this._takeUid(dropped)));
    if (key) this._commitKeys.add(key);
    this._committed.sort(sortWindow);

    this._watermarkMs = Math.max(this._watermarkMs, ev.t1_ms);
    const before = this._drafts.length;
    this._drafts = this._drafts.filter((d) => d.t1_ms > this._watermarkMs);
    const extra = before - this._drafts.length;
    return {
      accepted: true,
      dropped_drafts: dropped.length + extra,
      advanced_watermark: this._watermarkMs > oldWatermark,
    };
  }
}
