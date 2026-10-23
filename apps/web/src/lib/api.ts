import { runtimeEnv } from "@/lib/runtime-env";

/** A failed API call, carrying the server's error envelope. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null = null,
    readonly details: unknown = undefined,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Envelope = {
  error?: { code?: string; message?: string; request_id?: string; details?: unknown };
};

export function errorFrom(status: number, body: unknown): ApiError {
  const error = (body as Envelope | null)?.error;
  return new ApiError(
    status,
    error?.code ?? (status >= 500 ? "server_error" : "request_failed"),
    error?.message ?? "The request failed. Try again.",
    error?.request_id ?? null,
    error?.details,
  );
}

type RequestOptions = Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit };

export function apiUrl(path: string): string {
  return `${runtimeEnv().apiUrl}${path}`;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const { json, headers, ...rest } = options;
  try {
    return await fetch(apiUrl(path), {
      credentials: "include",
      ...rest,
      headers: {
        accept: "application/json",
        ...(json !== undefined ? { "content-type": "application/json" } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the AgentStudio API. Is it running?");
  }
}

async function failure(response: Response): Promise<ApiError> {
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  return errorFrom(response.status, body);
}

/** JSON over fetch with the session cookie; throws ApiError on any non-2xx response. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

/** A file from the API (Python export, original documents), with its suggested name. */
export async function apiFile(path: string): Promise<{ text: string; filename: string | null }> {
  const response = await send(path, { headers: { accept: "*/*" } });
  if (!response.ok) throw await failure(response);
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return { text: await response.text(), filename: match?.[1] ?? null };
}

export const ws = (workspace: string) => `/api/v1/workspaces/${encodeURIComponent(workspace)}`;

/** Save text as a file through a temporary link. */
export function saveText(text: string, filename: string, type = "text/plain"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  link.click();
  URL.revokeObjectURL(url);
}
