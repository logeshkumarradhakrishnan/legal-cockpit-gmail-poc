export const config = {
  apiBase: (import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, ""),
  authMode: (import.meta.env.VITE_AUTH_MODE ?? "dev") as "dev" | "entra",
  tenantId: import.meta.env.VITE_ENTRA_TENANT_ID ?? "",
  clientId: import.meta.env.VITE_ENTRA_CLIENT_ID ?? "",
  apiScope: import.meta.env.VITE_API_SCOPE ?? "",
};
