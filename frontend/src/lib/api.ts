/** Wrapper de fetch del sistema (CLAUDE.md: nada de axios).
 *
 * - Base /api/v1, credentials include (la cookie HttpOnly del refresh).
 * - Access token SOLO en memoria, inyectado en Authorization.
 * - 401 → refresh SINGLE-FLIGHT: todos los requests concurrentes esperan UNA
 *   sola promesa de refresh y reintentan UNA vez; si el refresh falla se
 *   limpia la sesión y se avisa (redirección a login la hace AuthContext).
 * - 403 password_change_required → callback para redirigir al cambio forzado.
 */

export const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly code: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

type Callback = () => void;
let onSesionExpirada: Callback = () => {};
let onPasswordChangeRequired: Callback = () => {};

export function configurarCallbacks(callbacks: {
  sesionExpirada?: Callback;
  passwordChangeRequired?: Callback;
}): void {
  if (callbacks.sesionExpirada) onSesionExpirada = callbacks.sesionExpirada;
  if (callbacks.passwordChangeRequired) onPasswordChangeRequired = callbacks.passwordChangeRequired;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
}

function construirUrl(path: string, params?: RequestOptions["params"]): string {
  const query = new URLSearchParams();
  for (const [clave, valor] of Object.entries(params ?? {})) {
    if (valor !== undefined && valor !== null && valor !== "") query.append(clave, String(valor));
  }
  const qs = query.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

// ---------------------------------------------------------- refresh single-flight

let refreshEnCurso: Promise<boolean> | null = null;

/** Un solo refresh vivo a la vez: quien llegue mientras corre, lo espera. */
export function refrescarToken(): Promise<boolean> {
  refreshEnCurso ??= (async () => {
    try {
      const r = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!r.ok) return false;
      const data = (await r.json()) as { access_token: string };
      accessToken = data.access_token;
      return true;
    } catch {
      return false;
    } finally {
      refreshEnCurso = null;
    }
  })();
  return refreshEnCurso;
}

// ------------------------------------------------------------------- request

async function ejecutar(url: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(url, {
    method: options.method ?? "GET",
    headers,
    credentials: "include",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
}

async function aError(response: Response): Promise<ApiError> {
  let detail = "Error de comunicación con el servidor";
  let code = "unknown_error";
  try {
    const data = (await response.json()) as { detail?: string; code?: string };
    if (typeof data.detail === "string") detail = data.detail;
    if (typeof data.code === "string") code = data.code;
  } catch {
    // cuerpo no-JSON: se conservan los defaults
  }
  return new ApiError(response.status, detail, code);
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = construirUrl(path, options.params);
  let response = await ejecutar(url, options);

  if (response.status === 401 && !path.startsWith("/auth/")) {
    const renovado = await refrescarToken();
    if (!renovado) {
      setAccessToken(null);
      onSesionExpirada();
      throw new ApiError(401, "Tu sesión expiró, vuelve a iniciar sesión", "session_expired");
    }
    response = await ejecutar(url, options); // reintento único
  }

  if (!response.ok) {
    const error = await aError(response);
    if (error.status === 401 && !path.startsWith("/auth/")) {
      setAccessToken(null);
      onSesionExpirada();
    }
    if (error.status === 403 && error.code === "password_change_required") {
      onPasswordChangeRequired();
    }
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
