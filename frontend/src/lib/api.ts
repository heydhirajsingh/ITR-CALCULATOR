export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const targetUrl = path.startsWith("http")
    ? path
    : `${BASE_URL}${path.startsWith("/") ? "" : "/"}${path}`;

  const response = await fetch(targetUrl, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      message = payload.detail || payload.error || message;
    } catch {
      // Keep the generic message.
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}
