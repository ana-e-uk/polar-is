import type { AvailabilityRow, Catalog, QueryForm, QueryJob, QueryResult, ServiceStatus } from "./types";

async function responseJson<T>(response: Response): Promise<T> {
  const body = await response.json();
  if (!response.ok) {
    const detail = body.detail;
    if (typeof detail === "string") throw new Error(detail);
    if (Array.isArray(detail)) {
      throw new Error(detail.map((item) => item.msg).join("; "));
    }
    throw new Error(`Request failed with status ${response.status}`);
  }
  return body as T;
}

export async function fetchCatalog(): Promise<Catalog> {
  return responseJson<Catalog>(await fetch("/api/catalog"));
}

export async function fetchAvailability(): Promise<AvailabilityRow[]> {
  const body = await responseJson<{ rows: AvailabilityRow[] }>(
    await fetch("/api/availability"),
  );
  return body.rows;
}

export async function fetchServiceStatus(): Promise<ServiceStatus> {
  return responseJson<ServiceStatus>(await fetch("/api/v1/status"));
}

export async function runQuery(
  form: QueryForm,
  onProgress?: (message: string) => void,
): Promise<QueryResult> {
  const isFilter = form.function === "find-time" || form.function === "find-area";
  const payload = {
    ...form,
    repository: form.repository || null,
    dataset: form.dataset || null,
    predicate: isFilter ? form.predicate : null,
    filter_value: isFilter && form.filter_value !== "" ? Number(form.filter_value) : null,
  };
  const created = await responseJson<QueryJob>(
    await fetch("/api/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: payload, outputs: ["plot-json", "netcdf"] }),
    }),
  );
  const report = (job: QueryJob) => {
    if (!onProgress) return;
    if (job.status === "queued") {
      const count = job.jobs_ahead ?? 0;
      onProgress(count > 0
        ? `${count} job${count === 1 ? "" : "s"} ahead of yours.`
        : "Your query is next in the queue.");
    } else if (job.status === "running") {
      onProgress("Your query is running.");
    }
  };
  report(created);
  for (;;) {
    const job = await responseJson<QueryJob>(await fetch(created.status_url));
    report(job);
    if (job.status === "completed" && job.result) return job.result;
    if (job.status === "failed" || job.status === "cancelled" || job.status === "expired") {
      throw new Error(job.error?.message ?? `Query job ${job.status}`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 350));
  }
}
