"""Shared contracts; no citation label or query enters an extractor."""

from dataclasses import asdict, dataclass, field
import hashlib
import json


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    payload_hash: str
    href: str
    hostname: str
    payload: str
    format: str


@dataclass
class CandidateResult:
    method: str
    status: str = "ok"
    html: str = ""
    text: str = ""
    markdown: str = ""
    metadata: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    blocks: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def snapshot_identity(payload, href):
    payload_hash = hashlib.sha256(payload.encode()).hexdigest()
    return payload_hash, stable_hash([payload_hash, href])
