"""
etsi_014_routes.py — ETSI GS QKD 014 REST interface for the DTPT Framework (Phase 4)

Endpoints (ETSI GS QKD 014 v1.1.1, Section 5):
    GET  /api/v1/keys/{slave_SAE_ID}/status     channel status + decoy-state health
    POST /api/v1/keys/{slave_SAE_ID}/enc_keys   master SAE (Alice) starts a signature session
    GET  /api/v1/keys/{master_SAE_ID}/dec_keys  slave SAE (Bob) retrieves the verified key
                                                 ?key_ID=<transaction_id>

Watchdog gate: dec_keys runs the ordered Watchdog on the stored session. Any
ABORT_* exception is caught and answered with HTTP 403 and the abort status;
the key material is never serialised for a compromised session.

Deviations from strict ETSI 014 (documented for the judges):
  * enc_keys returns the key_ID with status PENDING and NO key material: in
    DTPT the key is released only after the Watchdog verifies it at dec_keys.
  * DTPT telemetry travels in the ETSI extension fields
    (`key_container_extension`, `key_extension`).

mTLS (mocked): a TLS-terminating proxy is assumed to verify the client
certificate and forward its SHA-256 fingerprint in X-SSL-Client-Cert-SHA256.
The fingerprint must match a node in the NodeRegistry (401 otherwise), and the
node's role must be allowed on the endpoint (403 otherwise).

Demo-only router: POST /api/v1/simulate/attack drives the Attack Simulation Harness.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from watchdog.attack_simulation_harness import (
    WATCHDOG_EXCEPTIONS,
    AttackType,
    ChannelSettings,
    SessionTelemetry,
    assess_signature_session,
    evaluate_signature_session,
    execute_honest_signature,
    simulate_attack,
)
from watchdog.decoy_stats import assess_decoy_telemetry

CLIENT_CERT_HEADER: Final[str] = "X-SSL-Client-Cert-SHA256"
KME_ID: Final[str] = "DTPT_KME_CHARLIE_HUB"
MAX_KEY_SIZE_BITS: Final[int] = 4096
MIN_KEY_SIZE_BITS: Final[int] = 64
DEFAULT_KEY_SIZE_BITS: Final[int] = 256
MAX_STORED_SESSIONS: Final[int] = 500


# ---------------------------------------------------------------------------
# Node registry (mock mTLS)
# ---------------------------------------------------------------------------


class NodeRole(str, Enum):
    SENDER = "SENDER"
    RECEIVER = "RECEIVER"
    UNTRUSTED_ROUTER = "UNTRUSTED_ROUTER"


@dataclass(frozen=True)
class RegisteredNode:
    sae_id: str
    role: NodeRole
    tls_cert_hash: str


def demo_certificate_hash(sae_id: str) -> str:
    """Deterministic demo fingerprint. Replace with real certificate SHA-256 values in deployment."""
    return hashlib.sha256(f"dtpt-demo-cert:{sae_id}".encode()).hexdigest()


_DEMO_NODES: Final[tuple[tuple[str, NodeRole], ...]] = (
    ("ALICE_SAE_01", NodeRole.SENDER),
    ("BOB_SAE_01", NodeRole.RECEIVER),
    ("CHARLIE_ROUTER_01", NodeRole.UNTRUSTED_ROUTER),
)

NODE_REGISTRY: Final[dict[str, RegisteredNode]] = {
    demo_certificate_hash(sae_id): RegisteredNode(sae_id, role, demo_certificate_hash(sae_id))
    for sae_id, role in _DEMO_NODES
}
NODES_BY_SAE_ID: Final[dict[str, RegisteredNode]] = {node.sae_id: node for node in NODE_REGISTRY.values()}


def authenticate_node(
    client_cert_hash: Annotated[str | None, Header(alias=CLIENT_CERT_HEADER)] = None,
) -> RegisteredNode:
    """Mocked mTLS: unknown or missing fingerprints are rejected with 401."""
    node = NODE_REGISTRY.get((client_cert_hash or "").strip().lower())
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client certificate is not registered in the NodeRegistry (mTLS authentication failed).",
        )
    return node


def require_role(node: RegisteredNode, *allowed: NodeRole) -> None:
    if node.role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Node {node.sae_id} with role {node.role.value} may not call this endpoint.",
        )


def registered_counterpart(sae_id: str, expected_role: NodeRole) -> RegisteredNode:
    node = NODES_BY_SAE_ID.get(sae_id)
    if node is None or node.role is not expected_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SAE {sae_id!r} is not a registered {expected_role.value}.",
        )
    return node


# ---------------------------------------------------------------------------
# Session store (in-memory SignatureLogs)
# ---------------------------------------------------------------------------


@dataclass
class SignatureSession:
    transaction_id: str
    master_sae_id: str
    slave_sae_id: str
    key_size: int
    telemetry: SessionTelemetry
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "PENDING"

    def log_row(self) -> dict[str, Any]:
        """Row shaped like the SignatureLogs table in DATA_MODEL.md."""
        return {
            "transaction_id": self.transaction_id,
            "sae_id": self.slave_sae_id,
            "mismatch_rate": self.telemetry.mismatch_rate,
            "state_fidelity": self.telemetry.batch_state_fidelity,
            "status": self.status,
            "timestamp": self.created_at.isoformat(),
        }


class SessionStore:
    """Thread-safe bounded store; FastAPI runs sync endpoints in a thread pool."""

    def __init__(self, capacity: int = MAX_STORED_SESSIONS) -> None:
        self._sessions: dict[str, SignatureSession] = {}
        self._lock = threading.Lock()
        self._capacity = capacity

    def add(self, session: SignatureSession) -> None:
        with self._lock:
            if len(self._sessions) >= self._capacity:
                oldest = min(self._sessions.values(), key=lambda s: s.created_at)
                del self._sessions[oldest.transaction_id]
            self._sessions[session.transaction_id] = session

    def get(self, transaction_id: str) -> SignatureSession | None:
        with self._lock:
            return self._sessions.get(transaction_id)

    def latest_for_pair(self, master_sae_id: str, slave_sae_id: str) -> SignatureSession | None:
        with self._lock:
            matches = [
                s for s in self._sessions.values()
                if s.master_sae_id == master_sae_id and s.slave_sae_id == slave_sae_id
            ]
        return max(matches, key=lambda s: s.created_at) if matches else None

    def set_status(self, transaction_id: str, new_status: str) -> None:
        with self._lock:
            if transaction_id in self._sessions:
                self._sessions[transaction_id].status = new_status


session_store = SessionStore()


@lru_cache(maxsize=1)
def get_channel_settings() -> ChannelSettings:
    """Calibrated channel from environment (defaults: 100 km, p = 0.02, L = 4096)."""
    return ChannelSettings(
        key_length=int(os.getenv("DTPT_KEY_LENGTH", "4096")),
        depolarizing_probability=float(os.getenv("DTPT_DEPOLARIZING_P", "0.02")),
        amplitude_damping_gamma=float(os.getenv("DTPT_AMPLITUDE_DAMPING_GAMMA", "0.0")),
        decoy_pulse_count=int(os.getenv("DTPT_DECOY_PULSES", "1000000")),
    )


def derive_key_material(session: SignatureSession) -> str:
    """Base64 key bits bound to the verified token string and transaction ID (SHAKE-256 expansion)."""
    shake = hashlib.shake_256()
    shake.update(session.transaction_id.encode())
    shake.update(session.telemetry.token_indices.astype("uint8").tobytes())
    return base64.b64encode(shake.digest(session.key_size // 8)).decode()


# ---------------------------------------------------------------------------
# ETSI 014 schemas
# ---------------------------------------------------------------------------


class KeyRequest(BaseModel):
    """ETSI 014 Key request. Only one key per request is supported in the prototype."""

    model_config = ConfigDict(extra="ignore")

    number: int = Field(default=1, ge=1, le=1)
    size: int = Field(default=DEFAULT_KEY_SIZE_BITS, ge=MIN_KEY_SIZE_BITS, le=MAX_KEY_SIZE_BITS, multiple_of=8)


class KeyItem(BaseModel):
    key_ID: str
    key: str | None = None
    key_extension: dict[str, Any] | None = None


class KeyContainer(BaseModel):
    keys: list[KeyItem]
    key_container_extension: dict[str, Any] | None = None


class StatusResponse(BaseModel):
    source_KME_ID: str
    target_KME_ID: str
    master_SAE_ID: str
    slave_SAE_ID: str
    key_size: int
    stored_key_count: int
    max_key_count: int
    max_key_per_request: int
    max_key_size: int
    min_key_size: int
    max_SAE_ID_count: int
    status_extension: dict[str, Any] | None = None


class AttackRequest(BaseModel):
    attack_type: AttackType
    master_SAE_ID: str = "ALICE_SAE_01"
    slave_SAE_ID: str = "BOB_SAE_01"


def forbidden(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=payload)


# ---------------------------------------------------------------------------
# ETSI 014 router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/keys", tags=["ETSI GS QKD 014"])

SaeIdPath = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")]


@router.get("/{slave_SAE_ID}/status", response_model=StatusResponse)
def get_status(
    slave_SAE_ID: SaeIdPath,
    node: Annotated[RegisteredNode, Depends(authenticate_node)],
) -> StatusResponse:
    """Channel status for master (caller) -> slave. isValid comes from the latest decoy-state telemetry."""
    require_role(node, NodeRole.SENDER)
    registered_counterpart(slave_SAE_ID, NodeRole.RECEIVER)
    settings = get_channel_settings()
    latest = session_store.latest_for_pair(node.sae_id, slave_SAE_ID)

    extension: dict[str, Any] = {"isValid": None, "latest_transaction_id": None}
    if latest is not None:
        decoy_assessment = assess_decoy_telemetry(latest.telemetry.decoy_telemetry)
        extension = {
            "isValid": decoy_assessment.is_secure,
            "latest_transaction_id": latest.transaction_id,
            **latest.telemetry.decoy_telemetry.to_record(),
        }

    return StatusResponse(
        source_KME_ID=KME_ID,
        target_KME_ID=KME_ID,
        master_SAE_ID=node.sae_id,
        slave_SAE_ID=slave_SAE_ID,
        key_size=DEFAULT_KEY_SIZE_BITS,
        stored_key_count=0 if latest is None else 1,
        max_key_count=MAX_STORED_SESSIONS,
        max_key_per_request=1,
        max_key_size=MAX_KEY_SIZE_BITS,
        min_key_size=MIN_KEY_SIZE_BITS,
        max_SAE_ID_count=0,
        status_extension={**extension, "signature_token_length": settings.key_length},
    )


@router.post("/{slave_SAE_ID}/enc_keys", response_model=KeyContainer)
def post_enc_keys(
    slave_SAE_ID: SaeIdPath,
    node: Annotated[RegisteredNode, Depends(authenticate_node)],
    request: KeyRequest | None = None,
) -> KeyContainer:
    """Alice starts a teleportation-based signature session toward Bob."""
    require_role(node, NodeRole.SENDER)
    registered_counterpart(slave_SAE_ID, NodeRole.RECEIVER)
    request = request or KeyRequest()

    session = SignatureSession(
        transaction_id=str(uuid.uuid4()),
        master_sae_id=node.sae_id,
        slave_sae_id=slave_SAE_ID,
        key_size=request.size,
        telemetry=execute_honest_signature(get_channel_settings()),
    )
    session_store.add(session)

    return KeyContainer(
        keys=[KeyItem(key_ID=session.transaction_id, key_extension={"status": "PENDING"})],
        key_container_extension={
            "transaction_id": session.transaction_id,
            "status": "PENDING",
            "detail": "Key material is released to the slave SAE via dec_keys after Watchdog verification.",
        },
    )


@router.get("/{master_SAE_ID}/dec_keys", response_model=KeyContainer, responses={403: {"description": "Watchdog abort"}})
def get_dec_keys(
    master_SAE_ID: SaeIdPath,
    node: Annotated[RegisteredNode, Depends(authenticate_node)],
    key_ID: Annotated[str, Query(min_length=1, max_length=64)],
) -> KeyContainer | JSONResponse:
    """Bob retrieves the verified key. Compromised sessions return 403 with the ABORT_* status."""
    require_role(node, NodeRole.RECEIVER)

    session = session_store.get(key_ID)
    # Row-level security: only the slave SAE of this transaction, with the right master, may see it.
    if session is None or session.slave_sae_id != node.sae_id or session.master_sae_id != master_SAE_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown key_ID for this SAE pair.")

    try:
        report = evaluate_signature_session(session.telemetry)
    except WATCHDOG_EXCEPTIONS as threat:
        session_store.set_status(session.transaction_id, threat.abort_status)
        return forbidden({**threat.to_payload(), "key_ID": session.transaction_id})

    session_store.set_status(session.transaction_id, report.status)
    return KeyContainer(
        keys=[
            KeyItem(
                key_ID=session.transaction_id,
                key=derive_key_material(session),
                key_extension={"status": report.status},
            )
        ],
        key_container_extension={
            "status": report.status,
            "state_fidelity": session.telemetry.batch_state_fidelity,
            "mismatch_rate": session.telemetry.mismatch_rate,
            "s_a": session.telemetry.thresholds.s_a,
            "s_v": session.telemetry.thresholds.s_v,
        },
    )


# ---------------------------------------------------------------------------
# Demo-only attack simulation router
# ---------------------------------------------------------------------------

simulation_router = APIRouter(prefix="/api/v1/simulate", tags=["Attack Simulation (demo only)"])


@simulation_router.post("/attack")
def post_simulate_attack(request: AttackRequest) -> dict[str, Any]:
    """
    Run one session with the requested attack (or NONE for the honest baseline),
    store it under the given SAE pair, and return the Watchdog verdict plus chart
    data. Retrieving the same key_ID via dec_keys then yields the 403.
    """
    registered_counterpart(request.master_SAE_ID, NodeRole.SENDER)
    registered_counterpart(request.slave_SAE_ID, NodeRole.RECEIVER)

    telemetry = simulate_attack(request.attack_type, get_channel_settings())
    report = assess_signature_session(telemetry)
    session = SignatureSession(
        transaction_id=str(uuid.uuid4()),
        master_sae_id=request.master_SAE_ID,
        slave_sae_id=request.slave_SAE_ID,
        key_size=DEFAULT_KEY_SIZE_BITS,
        telemetry=telemetry,
        status=report.status,
    )
    session_store.add(session)

    return {
        "transaction_id": session.transaction_id,
        "attack_type": request.attack_type.value,
        "watchdog": report.to_payload(),
        "telemetry": telemetry.to_payload(include_distributions=True),
        "signature_log": session.log_row(),
    }
