const GITHUB_API = "https://api.github.com";
const API_VERSION = "2026-03-10";
const ACTIVE_STATUSES = ["queued", "in_progress", "waiting", "pending", "requested"];
const REQUEST_TIMEOUT_MS = 10_000;

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
    workflowPath: `/repos/${env.GITHUB_REPOSITORY}/actions/workflows/${encodeURIComponent(env.GITHUB_WORKFLOW)}`,
    ref: env.GITHUB_REF,
    token: env.GITHUB_TOKEN.trim(),
  };
}

async function githubRequest(path, { token, method = "GET", body, fetchImpl, timeoutMs }) {
  const stage = method === "GET" ? "list_runs" : "dispatch";
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
      redirect: "error",
      signal: controller.signal,
    });

    const accepted = method === "GET" ? [200] : [200, 204];
    if (!accepted.includes(response.status)) {
      // Never log the response body, headers, token, or raw upstream errors.
      throw new SchedulerError(`${stage}_http_${response.status}`);
    }
    if (method !== "GET") return;

    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new SchedulerError(controller.signal.aborted ? `${stage}_timeout` : `${stage}_invalid_json`);
    }
    if (
      !Number.isInteger(payload?.total_count) ||
      payload.total_count < 0 ||
      !Array.isArray(payload.workflow_runs)
    ) {
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

export async function runScheduledRefresh(
  env,
  { fetchImpl = fetch, timeoutMs = REQUEST_TIMEOUT_MS } = {},
) {
  const { workflowPath, ref, token } = configuration(env);
  const requestOptions = { token, fetchImpl, timeoutMs };

  // Query each active status directly so a long-running build is not hidden by
  // a page of newer completed runs. Includes both native cron and manual runs.
  for (const status of ACTIVE_STATUSES) {
    const query = new URLSearchParams({ branch: ref, status, per_page: "1" });
    const runs = await githubRequest(`${workflowPath}/runs?${query}`, requestOptions);
    if (runs.total_count > 0 || runs.workflow_runs.length > 0) {
      return { status: "skipped", reason: "active_workflow", active_status: status };
    }
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
