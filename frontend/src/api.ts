import type { AppConfig } from "./types";

const API = import.meta.env.VITE_API_URL || "/api";

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = sessionStorage.getItem("access_token");
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    if (response.status === 401) {
      sessionStorage.removeItem("access_token");
      window.dispatchEvent(new Event("auth-expired"));
    }
    const error = await response.json().catch(() => ({}));
    const detail = error.detail;
    throw new Error(
      Array.isArray(detail)
        ? detail
            .map(
              (e: { loc: string[]; msg: string }) =>
                `${e.loc.at(-1)}: ${e.msg}`,
            )
            .join(". ")
        : typeof detail === "string"
          ? detail
          : `Request failed (${response.status})`,
    );
  }
  return response.json();
}

export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });

function base64url(buffer: Uint8Array) {
  return btoa(String.fromCharCode(...buffer))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

export async function signIn(config: AppConfig) {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(48)));
  const state = base64url(crypto.getRandomValues(new Uint8Array(24)));
  const challenge = base64url(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)),
    ),
  );
  sessionStorage.setItem("pkce_verifier", verifier);
  sessionStorage.setItem("oauth_state", state);
  const params = new URLSearchParams({
    client_id: config.cognito_client_id,
    response_type: "code",
    scope: "openid email profile",
    redirect_uri: `${location.origin}/`,
    code_challenge_method: "S256",
    code_challenge: challenge,
    state,
  });
  location.assign(`${config.cognito_domain}/oauth2/authorize?${params}`);
}

export async function completeSignIn(config: AppConfig) {
  const params = new URLSearchParams(location.search);
  if (params.has("error"))
    throw new Error(params.get("error_description") || "Sign-in was declined");
  if (!params.has("code")) return;
  const verifier = sessionStorage.getItem("pkce_verifier");
  if (
    !verifier ||
    params.get("state") !== sessionStorage.getItem("oauth_state")
  ) {
    throw new Error("Sign-in verification failed. Please start again.");
  }
  const response = await fetch(`${config.cognito_domain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.cognito_client_id,
      code: params.get("code")!,
      redirect_uri: `${location.origin}/`,
      code_verifier: verifier,
    }),
  });
  if (!response.ok)
    throw new Error("Could not complete sign-in. Please try again.");
  const tokens = await response.json();
  sessionStorage.setItem("access_token", tokens.access_token);
  sessionStorage.removeItem("pkce_verifier");
  sessionStorage.removeItem("oauth_state");
  history.replaceState({}, "", "/");
}

export function signOut(config: AppConfig) {
  sessionStorage.removeItem("access_token");
  location.assign(
    `${config.cognito_domain}/logout?${new URLSearchParams({
      client_id: config.cognito_client_id,
      logout_uri: `${location.origin}/`,
    })}`,
  );
}
