/**
 * api.js — Axios client for the DTPT FastAPI backend (Render) with route-aware mock mTLS.
 *
 * A request interceptor attaches X-SSL-Client-Cert-SHA256 based on the endpoint:
 *   /api/v1/keys/{id}/dec_keys   -> Bob   (slave SAE, RECEIVER)
 *   /api/v1/keys/{id}/enc_keys   -> Alice (master SAE, SENDER)
 *   /api/v1/keys/{id}/status     -> Alice
 *   /api/v1/simulate/*, /health  -> no certificate header
 * A call can override this with `config.saeIdentity = "ALICE" | "BOB" | "NONE"`.
 *
 * DEMO ONLY: these fingerprints ship inside the public JS bundle, so anyone can
 * read them. Real mTLS proves identity in the TLS handshake, not in a header.
 */
import axios from "axios";

const RAW_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_DTPT_API_URL ?? "http://localhost:8000";
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, ""); // avoid "//api/v1/..." paths

export const CLIENT_CERT_HEADER = "X-SSL-Client-Cert-SHA256";
const REQUEST_TIMEOUT_MS = 60000; // generous: covers a Render cold start if the pinger misses

export const DEMO_SAE = Object.freeze({
  ALICE: {
    id: "ALICE_SAE_01",
    certHash: "7b6f2291eb1af5d0016cd2fb3470bf8c9b971fdad4aded13b8e0867a48903454",
  },
  BOB: {
    id: "BOB_SAE_01",
    certHash: "7039ffa2b919929187a480b99cf9eaea9d13076aa9a2277f1d8eb4a68360337a",
  },
});

export const ATTACK_TYPES = Object.freeze({
  NONE: "NONE",
  FORGERY: "FORGERY",
  REPLAY: "REPLAY",
  INTERCEPT_RESEND: "INTERCEPT_RESEND",
  PNS: "PNS",
});

if (import.meta.env.PROD && /localhost|127\.0\.0\.1/.test(API_BASE_URL)) {
  // Vite inlines env vars at BUILD time: set VITE_API_BASE_URL on Vercel, then redeploy.
  console.error(`[DTPT] Production build is pointing at ${API_BASE_URL}. Set VITE_API_BASE_URL and redeploy.`);
}

// ---------------------------------------------------------------------------
// Route -> identity resolution
// ---------------------------------------------------------------------------

const ROUTE_IDENTITIES = [
  { pattern: /^\/api\/v1\/keys\/[^/]+\/dec_keys\/?$/, identity: "BOB" },
  { pattern: /^\/api\/v1\/keys\/[^/]+\/(enc_keys|status)\/?$/, identity: "ALICE" },
  { pattern: /^\/api\/v1\/simulate\//, identity: "NONE" },
  { pattern: /^\/health\/?$/, identity: "NONE" },
];

/** Path of a request URL, whether it is relative ("/api/...") or absolute. */
export function requestPath(url = "", baseURL = API_BASE_URL) {
  try {
    return new URL(url, `${baseURL}/`).pathname;
  } catch {
    return url.split("?")[0];
  }
}

/** "ALICE" | "BOB" | "NONE" for a given path. Unknown routes get no certificate. */
export function resolveIdentity(path) {
  return ROUTE_IDENTITIES.find(({ pattern }) => pattern.test(path))?.identity ?? "NONE";
}

// ---------------------------------------------------------------------------
// Client + interceptors
// ---------------------------------------------------------------------------

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const identity = config.saeIdentity ?? resolveIdentity(requestPath(config.url, config.baseURL ?? API_BASE_URL));
  if (identity === "NONE") {
    config.headers.delete(CLIENT_CERT_HEADER);
  } else {
    config.headers.set(CLIENT_CERT_HEADER, DEMO_SAE[identity].certHash);
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      const path = requestPath(error.config?.url, error.config?.baseURL ?? API_BASE_URL);
      const sent = error.config?.headers?.get?.(CLIENT_CERT_HEADER);
      console.error(
        `[DTPT] mTLS 401 on ${path}. Header ${sent ? "WAS sent by the browser" : "was NOT sent"}` +
        (sent ? " — check whether a proxy stripped it before FastAPI." : " — check the interceptor route table."),
      );
    }
    return Promise.reject(error);
  },
);

// ---------------------------------------------------------------------------
// Endpoint helpers (same signatures as before; Dashboard.jsx needs no change)
// ---------------------------------------------------------------------------

/** GET /health */
export async function checkHealth() {
  const { data } = await apiClient.get("/health");
  return data;
}

/** ETSI: Alice starts a signature session toward Bob. Returns the key_ID (transaction ID). */
export async function requestSignature(slaveSaeId = DEMO_SAE.BOB.id, sizeBits = 256) {
  const { data } = await apiClient.post(`/api/v1/keys/${encodeURIComponent(slaveSaeId)}/enc_keys`, {
    number: 1,
    size: sizeBits,
  });
  return { keyId: data.keys[0].key_ID, container: data };
}

/** ETSI: channel status (decoy-state health) for Alice -> Bob. */
export async function getChannelStatus(slaveSaeId = DEMO_SAE.BOB.id) {
  const { data } = await apiClient.get(`/api/v1/keys/${encodeURIComponent(slaveSaeId)}/status`);
  return data;
}

/**
 * ETSI: Bob retrieves the key. 403 is a meaningful outcome (Watchdog abort), so it
 * resolves instead of throwing: { ok, httpStatus, data }.
 */
export async function retrieveVerifiedKey(keyId, masterSaeId = DEMO_SAE.ALICE.id) {
  const response = await apiClient.get(`/api/v1/keys/${encodeURIComponent(masterSaeId)}/dec_keys`, {
    params: { key_ID: keyId },
    validateStatus: (status) => status === 200 || status === 403,
  });
  return { ok: response.status === 200, httpStatus: response.status, data: response.data };
}

/** Demo harness: one session with the given attack (NONE = honest baseline). No certificate. */
export async function simulateAttack(attackType) {
  if (!Object.values(ATTACK_TYPES).includes(attackType)) {
    throw new Error(`Unknown attack type: ${attackType}`);
  }
  const { data } = await apiClient.post("/api/v1/simulate/attack", { attack_type: attackType });
  return data;
}

/** Human-readable message for network / HTTP errors. */
export function describeApiError(error) {
  if (error?.response) {
    const detail = error.response.data?.detail ?? error.response.data?.error ?? error.response.statusText;
    return `HTTP ${error.response.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`;
  }
  if (error?.code === "ECONNABORTED") {
    return `Request to ${API_BASE_URL} timed out (Render cold start?). Try again in a few seconds.`;
  }
  if (error?.request) {
    return `Backend unreachable at ${API_BASE_URL}, or blocked by CORS (see browser console).`;
  }
  return error?.message ?? "Unknown error";
}
