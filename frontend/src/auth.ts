/**
 * Sign-in.
 *  entra: MSAL redirect sign-in; every API call carries an access token for the API scope.
 *  dev:   no sign-in; the chosen sample user is sent as X-Dev-User (demos only).
 */
import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
} from "@azure/msal-browser";
import { config } from "./config";

let msal: PublicClientApplication | null = null;
let account: AccountInfo | null = null;

const DEV_KEY = "legalCockpit.devUser";

export function getDevUser(): string {
  try {
    return localStorage.getItem(DEV_KEY) ?? "gc@example.com";
  } catch {
    return "gc@example.com";
  }
}

export function setDevUser(email: string) {
  try {
    localStorage.setItem(DEV_KEY, email);
  } catch {
    /* storage unavailable: the switch lasts for this page only */
  }
}

/** Resolves once the user is signed in (entra) or immediately (dev). */
export async function initAuth(): Promise<void> {
  if (config.authMode !== "entra") return;
  if (!config.clientId || !config.tenantId || !config.apiScope) {
    throw new Error("Entra sign-in is not configured: set VITE_ENTRA_* and VITE_API_SCOPE.");
  }
  msal = new PublicClientApplication({
    auth: {
      clientId: config.clientId,
      authority: `https://login.microsoftonline.com/${config.tenantId}`,
      redirectUri: window.location.origin,
    },
    cache: { cacheLocation: "sessionStorage" },
  });
  await msal.initialize();
  const result = await msal.handleRedirectPromise();
  account = result?.account ?? msal.getAllAccounts()[0] ?? null;
  if (!account) {
    await msal.loginRedirect({ scopes: [config.apiScope] });
    return new Promise(() => {}); // the page navigates away
  }
  msal.setActiveAccount(account);
}

export async function authHeaders(): Promise<Record<string, string>> {
  if (config.authMode !== "entra") return { "X-Dev-User": getDevUser() };
  if (!msal || !account) throw new Error("Not signed in");
  try {
    const r = await msal.acquireTokenSilent({ scopes: [config.apiScope], account });
    return { Authorization: `Bearer ${r.accessToken}` };
  } catch (e) {
    if (e instanceof InteractionRequiredAuthError) {
      await msal.acquireTokenRedirect({ scopes: [config.apiScope], account });
    }
    throw e;
  }
}

export function signOut() {
  if (msal) msal.logoutRedirect();
}
