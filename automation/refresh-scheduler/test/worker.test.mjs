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
      ["queued", "in_progress", "waiting", "pending", "requested"],
    );
    for (const { url, options } of calls) {
      assert.equal(url.origin, "https://api.github.com");
      assert.equal(options.headers.Authorization, `Bearer ${env.GITHUB_TOKEN}`);
      assert.equal(options.redirect, "error");
      assert.ok(options.signal instanceof AbortSignal);
      if (options.method === "GET") {
        assert.equal(url.searchParams.get("branch"), "main");
        assert.equal(url.searchParams.get("per_page"), "1");
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
