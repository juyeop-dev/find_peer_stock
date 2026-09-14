import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import worker, { runScheduledRefresh } from "../src/worker.js";

const env = {
  GITHUB_REPOSITORY: "juyeop-dev/find_peer_stock",
  GITHUB_WORKFLOW: "build-site.yml",
  GITHUB_REF: "main",
  GITHUB_TOKEN: "fixture-only-not-a-credential",
};

const emptyRuns = () => Response.json({ total_count: 0, workflow_runs: [] });

for (const responseStatus of [200, 204]) {
  test(`dispatches a fresh build when no run is active (HTTP ${responseStatus})`, async () => {
    const calls = [];
    const result = await runScheduledRefresh(env, {
      fetchImpl: async (url, options) => {
        calls.push({ url: new URL(url), options });
        return options.method === "GET" ? emptyRuns() : new Response(null, { status: responseStatus });
      },
    });

    assert.deepEqual(result, { status: "dispatched" });
    assert.equal(calls.length, 6);
    assert.deepEqual(
      calls.slice(0, 5).map(({ url }) => url.searchParams.get("status")),
      ["in_progress", "waiting", "requested", "queued", "pending"],
    );
    for (const { url, options } of calls) {
      assert.equal(url.origin, "https://api.github.com");
      assert.equal(options.headers.Authorization, `Bearer ${env.GITHUB_TOKEN}`);
      assert.equal(options.redirect, "manual");
      assert.ok(options.signal instanceof AbortSignal);
      if (options.method === "GET") {
        assert.equal(url.searchParams.get("branch"), "main");
        const status = url.searchParams.get("status");
        assert.equal(url.searchParams.get("per_page"), ["queued", "pending"].includes(status) ? "100" : "1");
      }
    }
    const dispatch = calls.at(-1);
    assert.equal(dispatch.url.pathname, "/repos/juyeop-dev/find_peer_stock/actions/workflows/build-site.yml/dispatches");
    assert.deepEqual(JSON.parse(dispatch.options.body), { ref: "main", inputs: { force_fetch: true } });
  });
}

for (const status of ["queued", "in_progress", "waiting", "pending", "requested"]) {
  test(`skips dispatch if a ${status} run exists`, async () => {
    const result = await runScheduledRefresh(env, {
      fetchImpl: async (url, options) => {
        assert.equal(options.method, "GET", "must not dispatch while another run is active");
        return new URL(url).searchParams.get("status") === status
          ? Response.json({ total_count: 1, workflow_runs: [{ id: 42, status }] })
          : emptyRuns();
      },
    });
    assert.deepEqual(result, { status: "skipped", reason: "active_workflow", active_status: status });
  });
}

for (const status of [401, 403, 429, 500]) {
  test(`does not dispatch after an unsuccessful run check (HTTP ${status})`, async () => {
    let calls = 0;
    await assert.rejects(runScheduledRefresh(env, {
      fetchImpl: async (_url, options) => {
        calls++;
        assert.equal(options.method, "GET");
        return new Response(env.GITHUB_TOKEN, { status });
      },
    }), { message: `list_runs_http_${status}` });
    assert.equal(calls, 1);
  });
}

test("reports dispatch authentication failure without returning its body or token", async () => {
  await assert.rejects(runScheduledRefresh(env, {
    fetchImpl: async (_url, options) => options.method === "GET"
      ? emptyRuns()
      : new Response(env.GITHUB_TOKEN, { status: 401 }),
  }), { message: "dispatch_http_401" });
});

for (const status of [301, 302, 307, 308]) {
  for (const stage of ["list_runs", "dispatch"]) {
    test(`rejects ${stage} redirects (HTTP ${status}) without following them`, async () => {
      let calls = 0;
      await assert.rejects(runScheduledRefresh(env, {
        fetchImpl: async (url, options) => {
          calls++;
          assert.equal(new URL(url).origin, "https://api.github.com");
          assert.equal(options.redirect, "manual");
          if (stage === "dispatch" && options.method === "GET") return emptyRuns();
          return new Response(env.GITHUB_TOKEN, {
            status,
            headers: { Location: "https://example.com/must-not-receive-credentials" },
          });
        },
      }), { message: `${stage}_http_${status}` });
      assert.equal(calls, stage === "list_runs" ? 1 : 6);
    });
  }
}

test("missing or blank secret fails before making any request", async () => {
  for (const token of [undefined, "", "  "]) {
    await assert.rejects(runScheduledRefresh({ ...env, GITHUB_TOKEN: token }, {
      fetchImpl: async () => assert.fail("must not fetch without a secret"),
    }), { message: "missing_github_token" });
  }
});

test("a failed network request has a sanitized error", async () => {
  await assert.rejects(runScheduledRefresh(env, {
    fetchImpl: async () => { throw new Error(`sensitive upstream details ${env.GITHUB_TOKEN}`); },
  }), { message: "list_runs_network_error" });
});

test("a request timeout aborts the call and prevents dispatch", async () => {
  await assert.rejects(runScheduledRefresh(env, {
    timeoutMs: 5,
    fetchImpl: async (_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    }),
  }), { message: "list_runs_timeout" });
});

test("malformed run responses cannot be mistaken for no active runs", async () => {
  for (const payload of [{}, { total_count: 0 }, { total_count: "0", workflow_runs: [] }]) {
    await assert.rejects(runScheduledRefresh(env, {
      fetchImpl: async () => Response.json(payload),
    }), { message: "list_runs_invalid_response" });
  }
});

test("scheduled failure logs only a safe code", async (t) => {
  const logs = [];
  t.mock.method(console, "error", (message) => logs.push(message));
  t.mock.method(globalThis, "fetch", async () => { throw new Error(env.GITHUB_TOKEN); });

  await assert.rejects(worker.scheduled({}, env), { message: "list_runs_network_error" });
  assert.deepEqual(logs.map(JSON.parse), [{
    event: "refresh_scheduler", status: "error", code: "list_runs_network_error",
  }]);
});

const queueCheckTime = Date.parse("2026-09-13T03:00:00Z");
const oldQueuedRun = {
  id: 34718047492,
  workflow_id: 123456,
  head_branch: "main",
  path: ".github/workflows/build-site.yml",
  status: "queued",
  created_at: "2026-09-12T20:46:00Z",
  updated_at: "2026-09-12T20:46:00Z",
};

function queuedFetch({
  run = oldQueuedRun, runs, current, details,
  cancelStatus = 202, forceCancelStatus = 202, otherStatus,
} = {}) {
  const calls = [];
  const listedRuns = runs ?? [run];
  let detailIndex = 0;
  return {
    calls,
    fetchImpl: async (address, options) => {
      const url = new URL(address);
      calls.push({ url, options });
      if (url.pathname.endsWith("/force-cancel")) {
        assert.equal(options.method, "POST");
        return new Response(null, { status: forceCancelStatus });
      }
      if (url.pathname.endsWith("/cancel")) {
        assert.equal(options.method, "POST");
        return new Response(null, { status: cancelStatus });
      }
      assert.equal(options.method, "GET", "must not dispatch in a recovery invocation");
      const detail = url.pathname.match(/\/actions\/runs\/(\d+)$/);
      if (detail) {
        const selected = listedRuns.find((item) => item.id === Number(detail[1]));
        if (details) {
          assert.ok(detailIndex < details.length, "unexpected extra run detail request");
          return Response.json(details[detailIndex++]);
        }
        return Response.json(current ?? selected);
      }
      const status = url.searchParams.get("status");
      if (status === otherStatus) return Response.json({ total_count: 1, workflow_runs: [{ id: 99, status }] });
      const matching = listedRuns.filter((item) => item.status === status);
      return Response.json({ total_count: matching.length, workflow_runs: matching });
    },
  };
}

for (const status of ["queued", "pending"]) {
  test(`requests cancellation only for a verified ${status} run older than 45 minutes`, async () => {
    const run = { ...oldQueuedRun, status };
    const mock = queuedFetch({ run });
    const result = await runScheduledRefresh(env, { ...mock, now: queueCheckTime });
    assert.deepEqual(result, { status: "cancel_requested", reason: "stale_queue", run_id: run.id });
    assert.equal(mock.calls.at(-2).url.pathname, `/repos/${env.GITHUB_REPOSITORY}/actions/runs/${run.id}`);
    assert.equal(mock.calls.at(-1).url.pathname, `/repos/${env.GITHUB_REPOSITORY}/actions/runs/${run.id}/cancel`);
    assert.equal(mock.calls.filter(({ options }) => options.method === "POST").length, 1);
    assert.ok(mock.calls.length <= 7, "recovery has a bounded request count");
  });
}

test("a recent queue entry cannot hide a stale entry in the same status", async () => {
  const recentQueued = {
    ...oldQueuedRun, id: 34718047501,
    created_at: "2026-09-13T02:30:00Z", updated_at: "2026-09-13T02:30:00Z",
  };
  const staleQueued = {
    ...oldQueuedRun, id: 34718047502,
    created_at: "2026-09-12T21:00:00Z", updated_at: "2026-09-12T21:00:00Z",
  };
  const mock = queuedFetch({ runs: [recentQueued, staleQueued] });

  const result = await runScheduledRefresh(env, { ...mock, now: queueCheckTime });

  assert.deepEqual(result, {
    status: "cancel_requested", reason: "stale_queue", run_id: staleQueued.id,
  });
  assert.equal(mock.calls.at(-2).url.pathname,
    `/repos/${env.GITHUB_REPOSITORY}/actions/runs/${staleQueued.id}`);
  assert.equal(mock.calls.filter(({ url }) => url.pathname.endsWith("/cancel")).length, 1);
  assert.equal(mock.calls.length, 7, "queue scanning and one cancellation stay bounded");
});

test("selects the oldest valid stale candidate across both queue states", async () => {
  const staleQueued = {
    ...oldQueuedRun, id: 34718047502,
    created_at: "2026-09-12T21:00:00Z", updated_at: "2026-09-12T21:00:00Z",
  };
  const oldestPending = {
    ...oldQueuedRun, id: 34718047503, status: "pending",
    created_at: "2026-09-12T19:30:00Z", updated_at: "2026-09-12T19:30:00Z",
  };
  const invalidOlderPending = {
    ...oldQueuedRun, id: 34718047504, status: "pending", path: ".github/workflows/another.yml",
    created_at: "2026-09-12T18:00:00Z", updated_at: "2026-09-12T18:00:00Z",
  };
  const mock = queuedFetch({
    runs: [staleQueued, oldestPending, invalidOlderPending],
  });

  const result = await runScheduledRefresh(env, { ...mock, now: queueCheckTime });

  assert.deepEqual(result, {
    status: "cancel_requested", reason: "stale_queue", run_id: oldestPending.id,
  });
  const queueLists = mock.calls.filter(({ url }) => ["queued", "pending"].includes(url.searchParams.get("status")));
  assert.deepEqual(queueLists.map(({ url }) => url.searchParams.get("per_page")), ["100", "100"]);
  assert.equal(mock.calls.at(-2).url.pathname,
    `/repos/${env.GITHUB_REPOSITORY}/actions/runs/${oldestPending.id}`);
  assert.equal(mock.calls.at(-1).url.pathname,
    `/repos/${env.GITHUB_REPOSITORY}/actions/runs/${oldestPending.id}/cancel`);
  assert.equal(mock.calls.filter(({ url }) => url.pathname.endsWith("/cancel")).length, 1);
  assert.equal(mock.calls.length, 7, "queue scanning and one cancellation stay bounded");
});

test("running builds and approval waits prevent queue recovery regardless of age", async () => {
  for (const otherStatus of ["in_progress", "waiting", "requested"]) {
    const mock = queuedFetch({ otherStatus });
    assert.deepEqual(await runScheduledRefresh(env, { ...mock, now: queueCheckTime }), {
      status: "skipped", reason: "active_workflow", active_status: otherStatus,
    });
    assert.ok(mock.calls.every(({ options }) => options.method === "GET"));
  }
});

test("recent, malformed, future and mismatched queue entries cannot be canceled", async () => {
  const invalid = [
    { id: undefined }, { id: "34718047492" }, { id: -1 },
    { workflow_id: undefined }, { workflow_id: "123456" },
    { head_branch: "other-branch" }, { path: ".github/workflows/another.yml" },
    { created_at: undefined }, { created_at: "bad" }, { created_at: "2026-09-12T20:46:00" },
    { created_at: "2026-09-13T04:00:00Z" },
    { updated_at: "2026-09-13T02:30:00Z" },
    { updated_at: "2026-09-12T20:45:59Z" },
    { created_at: "2026-09-13T02:15:01Z", updated_at: "2026-09-13T02:15:01Z" },
  ];
  for (const changes of invalid) {
    const mock = queuedFetch({ run: { ...oldQueuedRun, ...changes } });
    assert.deepEqual(await runScheduledRefresh(env, { ...mock, now: queueCheckTime }), {
      status: "skipped", reason: "active_workflow", active_status: "queued",
    });
    assert.equal(mock.calls.length, 5, JSON.stringify(changes));
  }
});

test("a queue entry that changes identity or starts before cancellation is left alone", async () => {
  for (const changes of [
    { id: 999 }, { workflow_id: 999 }, { head_branch: "other-branch" },
    { path: ".github/workflows/another.yml" }, { status: "pending" }, { status: "in_progress" },
    { status: "completed" }, { status: "waiting" }, { updated_at: "2026-09-13T02:59:00Z" },
  ]) {
    const mock = queuedFetch({ current: { ...oldQueuedRun, ...changes } });
    assert.deepEqual(await runScheduledRefresh(env, { ...mock, now: queueCheckTime }), {
      status: "skipped", reason: "queue_state_changed",
    });
    assert.equal(mock.calls.length, 6);
    assert.ok(mock.calls.every(({ options }) => options.method === "GET"));
  }
});

test("a normal cancellation conflict force-cancels only after a second validation", async () => {
  const mock = queuedFetch({ cancelStatus: 409 });
  assert.deepEqual(await runScheduledRefresh(env, { ...mock, now: queueCheckTime }), {
    status: "force_cancel_requested", reason: "stale_queue", run_id: oldQueuedRun.id,
  });
  const targetPath = `/repos/${env.GITHUB_REPOSITORY}/actions/runs/${oldQueuedRun.id}`;
  assert.deepEqual(mock.calls.slice(-4).map(({ url }) => url.pathname), [
    targetPath, `${targetPath}/cancel`, targetPath, `${targetPath}/force-cancel`,
  ]);
  assert.equal(mock.calls.filter(({ options }) => options.method === "POST").length, 2);
  assert.equal(mock.calls.some(({ url }) => url.pathname.endsWith("/dispatches")), false);
  assert.equal(mock.calls.length, 9, "normal-conflict force recovery has a bounded maximum");
});

test("state or freshness changes after a normal cancellation conflict forbid force-cancel", async () => {
  const changesAfterConflict = [
    { id: 999 }, { workflow_id: 999 }, { head_branch: "other-branch" },
    { path: ".github/workflows/another.yml" }, { status: "pending" },
    { status: "in_progress" }, { updated_at: "2026-09-13T02:59:00Z" },
  ];
  for (const changes of changesAfterConflict) {
    const mock = queuedFetch({
      cancelStatus: 409,
      details: [oldQueuedRun, { ...oldQueuedRun, ...changes }],
    });
    assert.deepEqual(await runScheduledRefresh(env, { ...mock, now: queueCheckTime }), {
      status: "skipped", reason: "queue_state_changed",
    });
    assert.equal(mock.calls.filter(({ url }) => url.pathname.endsWith("/cancel")).length, 1);
    assert.equal(mock.calls.some(({ url }) => url.pathname.endsWith("/force-cancel")), false);
    assert.equal(mock.calls.some(({ url }) => url.pathname.endsWith("/dispatches")), false);
    assert.equal(mock.calls.length, 8, JSON.stringify(changes));
  }
});

test("a force-cancel conflict is final for the tick", async () => {
  const mock = queuedFetch({ cancelStatus: 409, forceCancelStatus: 409 });
  assert.deepEqual(await runScheduledRefresh(env, { ...mock, now: queueCheckTime }), {
    status: "conflict", reason: "queue_force_cancel_conflict", run_id: oldQueuedRun.id,
  });
  assert.equal(mock.calls.filter(({ url }) => url.pathname.endsWith("/force-cancel")).length, 1);
  assert.equal(mock.calls.some(({ url }) => url.pathname.endsWith("/dispatches")), false);
  assert.equal(mock.calls.length, 9);
});

test("cancellation failures have sanitized errors and never trigger a new build", async () => {
  const mock = queuedFetch({ cancelStatus: 403 });
  await assert.rejects(runScheduledRefresh(env, { ...mock, now: queueCheckTime }), {
    message: "cancel_run_http_403",
  });
  assert.equal(mock.calls.length, 7);
});

test("force-cancellation failures have sanitized errors and never trigger a new build", async () => {
  const mock = queuedFetch({ cancelStatus: 409, forceCancelStatus: 403 });
  await assert.rejects(runScheduledRefresh(env, { ...mock, now: queueCheckTime }), {
    message: "force_cancel_run_http_403",
  });
  assert.equal(mock.calls.some(({ url }) => url.pathname.endsWith("/dispatches")), false);
  assert.equal(mock.calls.length, 9);
});

test("a cancellation request is rechecked on the next tick before dispatch", async () => {
  const mock = queuedFetch();
  const first = await runScheduledRefresh(env, { ...mock, now: queueCheckTime });
  const second = await runScheduledRefresh(env, { ...mock, now: queueCheckTime + 300_000 });
  assert.equal(first.status, "cancel_requested");
  assert.equal(second.status, "cancel_requested");
  assert.equal(mock.calls.filter(({ url }) => url.pathname.endsWith("/cancel")).length, 2);
  const cleared = await runScheduledRefresh(env, {
    now: queueCheckTime + 600_000,
    fetchImpl: async (_url, options) => options.method === "GET" ? emptyRuns() : new Response(null, { status: 204 }),
  });
  assert.equal(cleared.status, "dispatched");
});

test("only a cron trigger is configured; no public HTTP mutation handler exists", async () => {
  const config = JSON.parse(await readFile(new URL("../wrangler.jsonc", import.meta.url), "utf8"));
  assert.deepEqual(config.triggers.crons, ["*/5 * * * *"]);
  assert.equal(config.workers_dev, false);
  assert.equal(config.preview_urls, false);
  assert.equal(config.routes, undefined);
  assert.equal(config.vars.GITHUB_TOKEN, undefined);
  assert.equal(worker.fetch, undefined);
  assert.equal(typeof worker.scheduled, "function");
});
