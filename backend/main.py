"""
main.py — FastAPI entry point for the DTPT Framework backend.

Run from the backend/ directory:
    uvicorn main:app --reload

Environment variables (all optional):
    DTPT_CORS_ORIGINS               comma-separated origins (default: CRA :3000 and Vite :5173)
    DTPT_ENABLE_ATTACK_SIMULATION   "true"/"false" — mount /api/v1/simulate (default true)
    DTPT_KEY_LENGTH, DTPT_DEPOLARIZING_P, DTPT_AMPLITUDE_DAMPING_GAMMA, DTPT_DECOY_PULSES
                                    channel calibration (see api/etsi_014_routes.py)

Real mTLS: terminate TLS at a proxy (or uvicorn with --ssl-keyfile, --ssl-certfile,
--ssl-ca-certs and --ssl-cert-reqs 2) and forward the client certificate's SHA-256
fingerprint in X-SSL-Client-Cert-SHA256.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.etsi_014_routes import CLIENT_CERT_HEADER, get_channel_settings, router as etsi_router, simulation_router
from watchdog.attack_simulation_harness import (
    calibrate_thresholds,
    intercept_fidelity_table,
    replay_fidelity_table,
)

logger = logging.getLogger("dtpt")

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"


def _env_flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _cors_origins() -> list[str]:
    return [origin.strip() for origin in os.getenv("DTPT_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Warm the Qiskit density-matrix caches so the first demo click is instant."""
    settings = get_channel_settings()
    thresholds = calibrate_thresholds(settings)
    intercept_fidelity_table(settings.depolarizing_probability, settings.amplitude_damping_gamma)
    replay_fidelity_table(settings.depolarizing_probability, settings.amplitude_damping_gamma)
    logger.info(
        "DTPT calibrated: L=%d, e_h=%.4f, s_a=%.4f, s_v=%.4f",
        settings.key_length, thresholds.honest_error_rate, thresholds.s_a, thresholds.s_v,
    )
    yield


app = FastAPI(
    title="DTPT Framework — Dual-Threshold Projective Teleportation",
    description="AI-free threat detection for teleportation-based Quantum Digital Signatures (SIH26141).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", CLIENT_CERT_HEADER],
)

app.include_router(etsi_router)
if _env_flag("DTPT_ENABLE_ATTACK_SIMULATION", True):
    app.include_router(simulation_router)


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "online"}
