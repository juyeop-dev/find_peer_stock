const GITHUB_API = "https://api.github.com";
const API_VERSION = "2026-03-10";
// Check running builds and approval waits before considering queue recovery.
const BLOCKING_STATUSES = ["in_progress", "waiting", "requested"];
const QUEUE_STATUSES = ["queued", "pending"];
const QUEUE_SCAN_LIMIT = 100;
const REQUEST_TIMEOUT_MS = 10_000;
const STALE_QUEUE_MS = 45 * 60_000;

class SchedulerError extends Error {
  constructor(code) {
    super(code);
    this.name = "SchedulerError";
    this.code = code;
  }
}

function configuration(env) {
  if (typeof env.GITHUB_TOKEN !== "string" || !env.GITHUB_TOKEN.trim()) {
    throw new SchedulerError("missing_github_token");
  }
  if (
    typeof env.GITHUB_REPOSITORY !== "string" ||
    !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(env.GITHUB_REPOSITORY) ||
    typeof env.GITHUB_WORKFLOW !== "string" ||
    !/^[A-Za-z0-9_.-]+\.ya?ml$/.test(env.GITHUB_WORKFLOW) ||
    typeof env.GITHUB_REF !== "string" ||
    !env.GITHUB_REF.trim()
  ) {
    throw new SchedulerError("invalid_configuration");
  }
  return {
    repositoryPath: `/repos/${env.GITHUB_REPOSITORY}`,
    workflowPath: `/repos/${env.GITHUB_REPOSITORY}/actions/workflows/${encodeURIComponent(env.GITHUB_WORKFLOW)}`,
    workflowFile: `.github/workflows/${env.GITHUB_WORKFLOW}`,
    ref: env.GITHUB_REF,
    token: env.GITHUB_TOKEN.trim(),
  };
}

async function githubRequest(path, {
  token, method = "GET", body, fetchImpl, timeoutMs,
  stage = method === "GET" ? "list_runs" : "dispatch",
  acceptedStatuses = method === "GET" ? [200] : [200, 204],
}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetchImpl(`${GITHUB_API}${path}`, {
      method,
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "find-peer-stock-refresh-scheduler",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
      // Workers rejects redirect: "error" before sending the request. Use
      // "manual" and reject every 3xx below; credentials never follow redirects.
      redirect: "manual",
      signal: controller.signal,
    });

    if (!acceptedStatuses.includes(response.status)) {
      // Never log the response body, headers, token, or raw upstream errors.
      throw new SchedulerError(`${stage}_http_${response.status}`);
    }
    if (method !== "GET") return response.status;

    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new SchedulerError(controller.signal.aborted ? `${stage}_timeout` : `${stage}_invalid_json`);
    }
    if (stage === "list_runs" && (
      !Number.isInteger(payload?.total_count) ||
      payload.total_count < 0 ||
      !Array.isArray(payload.workflow_runs)
    )) {
      throw new SchedulerError("list_runs_invalid_response");
    }
    return payload;
  } catch (error) {
    if (error instanceof SchedulerError) throw error;
    throw new SchedulerError(controller.signal.aborted ? `${stage}_timeout` : `${stage}_network_error`);
  } finally {
    clearTimeout(timeout);
  }
}

function staleQueueCandidate(run, config, now, workflowId = run?.workflow_id) {
  if (
    !["queued", "pending"].includes(run?.status) ||
    !Number.isSafeInteger(run.id) || run.id <= 0 ||
    !Number.isSafeInteger(run.workflow_id) || run.workflow_id <= 0 ||
    run.workflow_id !== workflowId ||
    run.head_branch !== config.ref ||
    typeof run.path !== "string" || run.path.split("@")[0] !== config.workflowFile
  ) return false;

  // A recently changed old run may be moving between jobs. Both timestamps
  // must show a settled queue, with an explicit timezone and no future values.
  const times = [run.created_at, run.updated_at].map((value) => (
    typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      ? Date.parse(value) : NaN
  ));
  return times[0] <= times[1] &&
    times.every((value) => Number.isFinite(value) && now - value >= STALE_QUEUE_MS);
}

function sameStaleQueueRun(run, expected, config, now) {
  return run?.id === expected.id &&
    run.workflow_id === expected.workflow_id &&
    run.head_branch === expected.head_branch &&
    run.path === expected.path &&
    run.status === expected.status &&
    staleQueueCandidate(run, config, now, expected.workflow_id);
}

async function recoverStaleQueue(run, config, requestOptions, now) {
  if (!staleQueueCandidate(run, config, now)) return null;
  const runPath = `${config.repositoryPath}/actions/runs/${run.id}`;
  const current = await githubRequest(runPath, { ...requestOptions, stage: "get_run" });
  if (!sameStaleQueueRun(current, run, config, now)) {
    return { status: "skipped", reason: "queue_state_changed" };
  }

  // Try the normal endpoint first. GitHub documents force-cancel as the
  // fallback when a run does not respond to normal cancellation.
  const responseStatus = await githubRequest(`${runPath}/cancel`, {
    ...requestOptions, method: "POST", stage: "cancel_run", acceptedStatuses: [202, 409],
  });
  if (responseStatus === 202) {
    return { status: "cancel_requested", reason: "stale_queue", run_id: run.id };
  }

  // A 409 may mean the queued run ignored normal cancellation. Re-read the
  // exact target after that response. Any identity, status, or freshness
  // change forbids force-cancel; this invocation also never dispatches.
  const rechecked = await githubRequest(runPath, {
    ...requestOptions, stage: "recheck_run_after_cancel_conflict",
  });
  if (!sameStaleQueueRun(rechecked, current, config, now)) {
    return { status: "skipped", reason: "queue_state_changed" };
  }

  const forceStatus = await githubRequest(`${runPath}/force-cancel`, {
    ...requestOptions, method: "POST", stage: "force_cancel_run", acceptedStatuses: [202, 409],
  });
  return forceStatus === 202
    ? { status: "force_cancel_requested", reason: "stale_queue", run_id: run.id }
    : { status: "conflict", reason: "queue_force_cancel_conflict", run_id: run.id };
}

function oldestStaleQueueCandidate(runs, config, now) {
  const candidates = runs.filter((run) => staleQueueCandidate(run, config, now));
  candidates.sort((left, right) => {
    for (const field of ["created_at", "updated_at"]) {
      const difference = Date.parse(left[field]) - Date.parse(right[field]);
      if (difference !== 0) return difference;
    }
    return left.id === right.id ? 0 : left.id < right.id ? -1 : 1;
  });
  return candidates[0] ?? null;
}

export async function runScheduledRefresh(
  env,
  { fetchImpl = fetch, timeoutMs = REQUEST_TIMEOUT_MS, now = Date.now() } = {},
) {
  const config = configuration(env);
  const { workflowPath, ref, token } = config;
  const requestOptions = { token, fetchImpl, timeoutMs };

  // A build that is actually running or awaiting approval always wins over
  // queue recovery. One result is enough because any such run blocks dispatch.
  for (const status of BLOCKING_STATUSES) {
    const query = new URLSearchParams({ branch: ref, status, per_page: "1" });
    const runs = await githubRequest(`${workflowPath}/runs?${query}`, requestOptions);
    if (runs.total_count > 0 || runs.workflow_runs.length > 0) {
      return { status: "skipped", reason: "active_workflow", active_status: status };
    }
  }

  // GitHub returns workflow runs newest first. Scan one maximum-sized, bounded
  // page for both queue states so a recent entry cannot hide an older stuck
  // entry. Select globally before issuing at most one individually verified
  // cancellation target in this invocation. The worst case is bounded at nine
  // API requests: three blocker checks, two queue lists, detail + normal cancel,
  // then detail + force-cancel after a normal-cancel conflict.
  const listedQueueRuns = [];
  let activeQueueStatus = null;
  for (const status of QUEUE_STATUSES) {
    const query = new URLSearchParams({
      branch: ref, status, per_page: String(QUEUE_SCAN_LIMIT),
    });
    const runs = await githubRequest(`${workflowPath}/runs?${query}`, requestOptions);
    if (runs.total_count > 0 || runs.workflow_runs.length > 0) {
      activeQueueStatus ??= status;
      listedQueueRuns.push(...runs.workflow_runs.slice(0, QUEUE_SCAN_LIMIT));
    }
  }
  const candidate = oldestStaleQueueCandidate(listedQueueRuns, config, now);
  if (candidate) return recoverStaleQueue(candidate, config, requestOptions, now);
  if (activeQueueStatus) {
    return { status: "skipped", reason: "active_workflow", active_status: activeQueueStatus };
  }

  await githubRequest(`${workflowPath}/dispatches`, {
    ...requestOptions,
    method: "POST",
    body: { ref, inputs: { force_fetch: true } },
  });
  return { status: "dispatched" };
}

export default {
  async scheduled(_controller, env) {
    try {
      const result = await runScheduledRefresh(env);
      console.info(JSON.stringify({ event: "refresh_scheduler", ...result }));
    } catch (error) {
      const code = error instanceof SchedulerError ? error.code : "unexpected_error";
      console.error(JSON.stringify({ event: "refresh_scheduler", status: "error", code }));
      // Mark the invocation failed in Cloudflare while exposing only a safe code.
      throw new Error(code);
    }
  },
};
