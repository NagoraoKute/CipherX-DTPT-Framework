import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    checkHealth: vi.fn(),
    simulateAttack: vi.fn(),
    retrieveVerifiedKey: vi.fn(),
    requestSignature: vi.fn(),
    getChannelStatus: vi.fn(),
  };
});

import * as api from "../api.js";
import Dashboard from "./Dashboard.jsx";

const sessionPayload = (attackType, status, mismatchVerdict = "AUTHENTICATED") => ({
  transaction_id: `txn-${attackType}`,
  attack_type: attackType,
  watchdog: {
    status,
    variant: null,
    decoy: {
      decoy_detections: 160, acceptance_interval: [100, 225], violations: [],
      single_photon_yield_lower_bound: 0.007, expected_single_photon_yield: 0.008,
    },
    mismatch: { s_a: 0.075, s_v: 0.12, mismatch_rate: status === "VERIFIED" ? 0.03 : 0.5, verdict: mismatchVerdict },
  },
  telemetry: {
    state_fidelity: 0.9706,
    mismatch_rate: status === "VERIFIED" ? 0.03 : 0.5,
    thresholds: { s_a: 0.075, s_v: 0.12 },
    mismatch_distribution: [{ mismatch_rate: 0.03, baseline: 1, observed: 1 }],
  },
});

beforeEach(() => {
  vi.clearAllMocks();
  api.checkHealth.mockResolvedValue({ status: "online" });
  api.simulateAttack.mockImplementation(async (type) =>
    type === "FORGERY" ? sessionPayload(type, "ABORT_FORGERY", "REJECTED") : sessionPayload(type, "VERIFIED"),
  );
  api.retrieveVerifiedKey.mockImplementation(async (keyId) =>
    keyId === "txn-FORGERY"
      ? { ok: false, httpStatus: 403, data: { error: "ABORT_FORGERY" } }
      : { ok: true, httpStatus: 200, data: { keys: [{ key: "a2V5" }], key_container_extension: {} } },
  );
});

describe("Dashboard (testing.md 1.2 / 5.1)", () => {
  it("renders the Sign Document button", async () => {
    render(<Dashboard />);
    expect(screen.getByRole("button", { name: /sign document/i })).toBeInTheDocument();
    await waitFor(() => expect(api.simulateAttack).toHaveBeenCalledWith("NONE"));
  });

  it("dispatches a FORGERY simulation and shows the 403 abort", async () => {
    render(<Dashboard />);
    await waitFor(() => expect(api.simulateAttack).toHaveBeenCalledWith("NONE"));
    await waitFor(() => expect(screen.getByRole("button", { name: /execute forgery/i })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: /execute forgery/i }));
    await waitFor(() => expect(api.simulateAttack).toHaveBeenCalledWith("FORGERY"));
    expect(await screen.findByTestId("etsi-gate")).toHaveTextContent("HTTP 403 Forbidden · ABORT_FORGERY");
  });
});
