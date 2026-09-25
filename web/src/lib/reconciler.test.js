import { expect, test } from "vitest";
import { Reconciler } from "./reconciler.js";

function cap(partial) {
  return {
    type: "caption",
    stage_id: "1",
    revision: 1,
    tier: 1,
    lang: "es",
    original: "",
    emitted_at_ms: 0,
    traces: [],
    ...partial,
  };
}

test("reconciler out-of-order converges", () => {
  const r = new Reconciler("1");
  r.apply(
    cap({ t0_ms: 100, t1_ms: 400, state: "draft", text: "A", revision: 1 }),
  );
  r.apply(
    cap({ t0_ms: 200, t1_ms: 500, state: "draft", text: "B", revision: 2 }),
  );
  r.apply(
    cap({
      t0_ms: 100,
      t1_ms: 500,
      state: "committed",
      text: "COMMIT_OK",
      revision: 1,
      tier: 2,
    }),
  );
  r.apply(
    cap({ t0_ms: 50, t1_ms: 300, state: "draft", text: "LATE", revision: 9 }),
  );

  const view = r.view();
  console.log("PASS reconciler out-of-order converges");
  console.log(
    `final=[${view.map((s) => s.state).join(",")}] count=${view.length} text="${view[0]?.text}"`,
  );

  expect(view).toHaveLength(1);
  expect(view[0].state).toBe("committed");
  expect(view[0].text).toBe("COMMIT_OK");
});

test("session and clause identity prevent duplicate commits after reconnect and switch", () => {
  const r = new Reconciler("1");
  const first = cap({ session_id: "old", clause_id: "a", t0_ms: 100, t1_ms: 400,
    state: "committed", text: "primero" });
  expect(r.apply(first).accepted).toBe(true);
  expect(r.apply({ ...first, provider: "local-gemma4", t0_ms: 120 }).reason).toBe("duplicate_commit");
  r.setSession("new");
  expect(r.view()).toHaveLength(0);
  expect(r.apply(first).reason).toBe("wrong_session");
  expect(r.apply({ ...first, session_id: "new", clause_id: "b", text: "nuevo" }).accepted).toBe(true);
  expect(r.committed().map((item) => item.text)).toEqual(["nuevo"]);
});

test("committed segments stay immutable and still clear overlapping drafts", () => {
  const r = new Reconciler("1");
  r.apply(
    cap({
      t0_ms: 100,
      t1_ms: 500,
      state: "committed",
      text: "FIRST",
      revision: 1,
    }),
  );
  r.apply(
    cap({ t0_ms: 450, t1_ms: 700, state: "draft", text: "pending" }),
  );
  r.apply(
    cap({
      t0_ms: 100,
      t1_ms: 500,
      state: "committed",
      text: "MUTATION",
      revision: 99,
    }),
  );

  expect(r.committed()).toHaveLength(1);
  expect(r.committed()[0].text).toBe("FIRST");
  expect(r.view().filter((segment) => segment.state === "draft")).toHaveLength(0);
});

test("live partial windows solidify one stable segment", () => {
  const r = new Reconciler("1");
  r.apply(cap({ t0_ms: 1000, t1_ms: 2500, state: "draft", text: "uno", revision: 1 }));
  const uid = r.view()[0].uid;
  r.apply(cap({ t0_ms: 1000, t1_ms: 4000, state: "draft", text: "uno dos", revision: 2 }));
  r.apply(cap({
    t0_ms: 1000,
    t1_ms: 4700,
    state: "committed",
    text: "Uno dos tres.",
    revision: 3,
    tier: 2,
  }));
  r.apply(cap({ t0_ms: 1000, t1_ms: 4000, state: "draft", text: "late", revision: 2 }));

  expect(r.view()).toHaveLength(1);
  expect(r.view()[0]).toMatchObject({
    uid,
    state: "committed",
    text: "Uno dos tres.",
  });
});
