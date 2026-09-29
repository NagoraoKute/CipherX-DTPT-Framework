/**
 * api.js — Axios clients for the DTPT FastAPI backend.
 *
 * Two clients:
 *   etsiClient        ETSI GS QKD 014 routes. Sends the mock mTLS fingerprint
 *                     (X-SSL-Client-Cert-SHA256). Defaults to Alice (master SAE).
 *   simulationClient  /api/v1/simulate/attack. No certificate header.
 *
 * Role note: ETSI dec_keys is called by the SLAVE SAE. The backend only lets a
 * RECEIVER fetch keys, so retrieveVerifiedKey() overrides the header with Bob's
 * fingerprint. Alice's fingerprint on dec_keys would get a 403 role error.
 *
 * Demo fingerprints only. In production the TLS proxy injects this header.
 */
import axios from "axios";

export const API_BASE_URL = import.meta.env.VITE_DTPT_API_URL ?? "http://localhost:8000";
export const CLIENT_CERT_HEADER = "X-SSL-Client-Cert-SHA256";
const REQUEST_TIMEOUT_MS = 20000;

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

export const etsiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: {
    "Content-Type": "application/json",
    [CLIENT_CERT_HEADER]: DEMO_SAE.ALICE.certHash,
  },
});

export const simulationClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: { "Content-Type": "application/json" },
});

/** GET /health */
export async function checkHealth() {
  const { data } = await simulationClient.get("/health");
  return data;
}

/** ETSI: Alice starts a signature session toward Bob. Returns the key_ID (transaction ID). */
export async function requestSignature(slaveSaeId = DEMO_SAE.BOB.id, sizeBits = 256) {
  const { data } = await etsiClient.post(`/api/v1/keys/${encodeURIComponent(slaveSaeId)}/enc_keys`, {
    number: 1,
    size: sizeBits,
  });
  return { keyId: data.keys[0].key_ID, container: data };
}

/** ETSI: channel status (decoy-state health) for Alice -> Bob. */
export async function getChannelStatus(slaveSaeId = DEMO_SAE.BOB.id) {
  const { data } = await etsiClient.get(`/api/v1/keys/${encodeURIComponent(slaveSaeId)}/status`);
  return data;
}

/**
 * ETSI: Bob retrieves the key. 403 is an expected, meaningful outcome (Watchdog abort),
 * so it is resolved rather than thrown: { ok, httpStatus, data }.
 */
export async function retrieveVerifiedKey(keyId, masterSaeId = DEMO_SAE.ALICE.id) {
  const response = await etsiClient.get(`/api/v1/keys/${encodeURIComponent(masterSaeId)}/dec_keys`, {
    params: { key_ID: keyId },
    headers: { [CLIENT_CERT_HEADER]: DEMO_SAE.BOB.certHash },
    validateStatus: (status) => status === 200 || status === 403,
  });
  return { ok: response.status === 200, httpStatus: response.status, data: response.data };
}

/** Demo harness: run one session with the given attack (NONE = honest baseline). No mTLS header. */
export async function simulateAttack(attackType) {
  if (!Object.values(ATTACK_TYPES).includes(attackType)) {
    throw new Error(`Unknown attack type: ${attackType}`);
  }
  const { data } = await simulationClient.post("/api/v1/simulate/attack", { attack_type: attackType });
  return data;
}

/** Human-readable message for network / HTTP errors. */
export function describeApiError(error) {
  if (error?.response) {
    const detail = error.response.data?.detail ?? error.response.data?.error ?? error.response.statusText;
    return `HTTP ${error.response.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`;
  }
  if (error?.request) {
    return `Backend unreachable at ${API_BASE_URL}. Is uvicorn running?`;
  }
  return error?.message ?? "Unknown error";
}
