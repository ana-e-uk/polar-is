import type { AvailabilityRow, Catalog, QueryForm, QueryResult } from "./types";

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

export async function runQuery(form: QueryForm): Promise<QueryResult> {
  const isFilter = form.function === "find-time" || form.function === "find-area";
  const payload = {
    ...form,
    repository: form.repository || null,
    dataset: form.dataset || null,
    predicate: isFilter ? form.predicate : null,
    filter_value: isFilter && form.filter_value !== "" ? Number(form.filter_value) : null,
  };
  return responseJson<QueryResult>(
    await fetch("/api/queries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}
