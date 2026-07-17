from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.adapters import prototype_snap_worker as snap_worker_module
from app.adapters.prototype_snap_worker import (
    PrototypeSnapWorker,
    PrototypeSnapWorkerError,
)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _write_worker_fixture(
    directory: Path,
    *,
    mode: str = "normal",
) -> tuple[Path, Path, Path]:
    source_payload = [
        {
            "path": "fixture/prototypeSnapWorker.ts",
            "hash": _sha256(b"fixture snap worker source"),
            "byteSize": len(b"fixture snap worker source"),
        }
    ]
    source_hash = _sha256(
        json.dumps(
            source_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    invocation_path = directory / "invocations.log"
    bundle = directory / "prototype_snap_worker.mjs"
    bundle_source = (
        """
import { createHash } from "node:crypto";
import { appendFile } from "node:fs/promises";

const protocolVersion = "prototype-snap-worker/v1";
const snapSolverVersion = "structured-prototype-freeform-snap/v1";
const expectedSourceHash = __SOURCE_HASH__;
const mode = __MODE__;
const invocationPath = __INVOCATION_PATH__;
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
await appendFile(invocationPath, `${process.pid}\n`, "utf8");

const digest = (value) =>
  `sha256:${createHash("sha256").update(value, "utf8").digest("hex")}`;
const responseSourceHash = mode === "wrong_identity"
  ? `sha256:${"0".repeat(64)}`
  : expectedSourceHash;
const response = {
  protocolVersion,
  requestId: request.requestId,
  action: request.action,
  status: "ok",
  snapSolverVersion,
  snapSolverSourceHash: responseSourceHash,
};

if (mode === "worker_error" && request.action === "attest") {
  response.status = "error";
  response.error = {
    code: "snap_attestation_mismatch",
    message: "snap evidence does not match deterministic replay",
  };
} else if (request.action === "describe") {
  response.result = {
    protocolVersion,
    snapSolverVersion,
    snapSolverSourceHash: expectedSourceHash,
  };
} else if (request.action === "attest") {
  response.result = {
    evidenceHash: mode === "wrong_hash"
      ? `sha256:${"0".repeat(64)}`
      : digest(request.evidenceJson),
  };
} else if (request.action === "attestMany") {
  const hashes = request.evidenceJsons.map(digest);
  response.result = {
    evidenceHashes: mode === "count_mismatch"
      ? hashes.slice(1)
      : mode === "reverse_hashes"
        ? hashes.reverse()
        : hashes,
  };
}

if (mode === "unexpected_field") response.unexpected = true;
process.stdout.write(JSON.stringify(response));
""".replace("__SOURCE_HASH__", json.dumps(source_hash))
        .replace("__MODE__", json.dumps(mode))
        .replace("__INVOCATION_PATH__", json.dumps(str(invocation_path)))
    )
    bundle.write_text(bundle_source, encoding="utf-8")
    bundle_bytes = bundle.read_bytes()
    manifest = directory / "prototype_snap_worker.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifestVersion": "prototype-snap-worker-manifest/v1",
                "protocolVersion": "prototype-snap-worker/v1",
                "snapSolverVersion": "structured-prototype-freeform-snap/v1",
                "snapSolverSourceHash": source_hash,
                "bundleFile": bundle.name,
                "bundleHash": _sha256(bundle_bytes),
                "bundleByteSize": len(bundle_bytes),
                "buildTool": "test-fixture/v1",
                "target": "node20",
                "sources": source_payload,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return manifest, bundle, invocation_path


def _node_executable() -> str:
    executable = shutil.which("node")
    assert executable is not None, "Node.js is required for snap worker tests"
    return executable


def _worker(
    *,
    manifest_path: Path,
    node_executable: str,
    attest_timeout_s: float = 1.0,
    attest_many_timeout_s: float = 10.0,
) -> PrototypeSnapWorker:
    return PrototypeSnapWorker(
        attest_timeout_s=attest_timeout_s,
        attest_many_timeout_s=attest_many_timeout_s,
        manifest_path=manifest_path,
        node_executable=node_executable,
    )


def test_worker_stdin_limit_covers_the_schema_bounded_200_entry_tail() -> None:
    assert snap_worker_module._MAX_STDIN_BYTES == 32 * 1024 * 1024


@pytest.mark.parametrize(
    ("attest_timeout_s", "attest_many_timeout_s", "message"),
    [
        (0.0, 60.0, "attest timeout"),
        (5.0, 0.0, "attestMany timeout"),
    ],
)
def test_worker_requires_positive_action_timeouts(
    attest_timeout_s: float,
    attest_many_timeout_s: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PrototypeSnapWorker(
            attest_timeout_s=attest_timeout_s,
            attest_many_timeout_s=attest_many_timeout_s,
        )


@pytest.mark.asyncio
async def test_worker_uses_distinct_live_and_recovery_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _bundle, _invocations = _write_worker_fixture(tmp_path)
    worker = _worker(
        manifest_path=manifest,
        node_executable=_node_executable(),
        attest_timeout_s=2.5,
        attest_many_timeout_s=45.5,
    )
    calls: list[tuple[str, float]] = []

    async def execute_spy(
        *,
        action: str,
        request: dict[str, object],
        response_model: object,
        timeout_s: float,
    ) -> object:
        del response_model
        calls.append((action, timeout_s))
        if action == "describe":
            result = type(
                "DescribeResult",
                (),
                {
                    "protocol_version": worker.identity.protocol_version,
                    "snap_solver_version": worker.identity.snap_solver_version,
                    "snap_solver_source_hash": worker.identity.snap_solver_source_hash,
                },
            )
        elif action == "attest":
            evidence_json = request["evidenceJson"]
            assert isinstance(evidence_json, str)
            result = type("AttestResult", (), {"evidence_hash": _sha256(evidence_json.encode())})
        else:
            evidence_jsons = request["evidenceJsons"]
            assert isinstance(evidence_jsons, list)
            result = type(
                "AttestManyResult",
                (),
                {
                    "evidence_hashes": [
                        _sha256(value.encode())
                        for value in evidence_jsons
                        if isinstance(value, str)
                    ]
                },
            )
        return type("WorkerResponse", (), {"result": result})

    monkeypatch.setattr(worker, "_execute", execute_spy)
    await worker.describe("describe-timeout")
    await worker.attest(request_id="live-timeout", evidence_json="{}")
    await worker.attest_many(request_id="recovery-timeout", evidence_jsons=["{}"])

    assert calls == [
        ("describe", 2.5),
        ("attest", 2.5),
        ("attestMany", 45.5),
    ]


@pytest.mark.asyncio
async def test_worker_describes_and_attests_exact_canonical_input_bytes(
    tmp_path: Path,
) -> None:
    manifest, _bundle, _invocations = _write_worker_fixture(tmp_path)
    worker = _worker(
        manifest_path=manifest,
        node_executable=_node_executable(),
    )
    evidence_json = '{"label":"\\u4e2d","position":{"x":"20.0000"}}'

    identity = await worker.describe("describe-fixture")
    attestation = await worker.attest(
        request_id="attest-fixture",
        evidence_json=evidence_json,
    )

    assert identity.protocol_version == "prototype-snap-worker/v1"
    assert identity.snap_solver_version == "structured-prototype-freeform-snap/v1"
    assert identity.snap_solver_source_hash.startswith("sha256:")
    assert identity.snap_solver_bundle_hash.startswith("sha256:")
    assert identity.snap_solver_bundle_byte_size > 0
    assert identity.build_tool == "test-fixture/v1"
    assert identity.target == "node20"
    assert attestation.evidence_hash == _sha256(evidence_json.encode("utf-8"))


@pytest.mark.asyncio
async def test_attest_many_preserves_order_and_uses_one_process(tmp_path: Path) -> None:
    manifest, _bundle, invocations = _write_worker_fixture(tmp_path)
    worker = _worker(
        manifest_path=manifest,
        node_executable=_node_executable(),
    )
    evidence_jsons = [f'{{"sequence":{sequence}}}' for sequence in range(199, -1, -1)]

    results = await worker.attest_many(
        request_id="attest-many-fixture",
        evidence_jsons=evidence_jsons,
    )

    assert [result.evidence_hash for result in results] == [
        _sha256(value.encode("utf-8")) for value in evidence_jsons
    ]
    assert len(invocations.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.asyncio
async def test_attest_many_refuses_more_than_200_entries_before_spawn(tmp_path: Path) -> None:
    manifest, _bundle, invocations = _write_worker_fixture(tmp_path)
    worker = _worker(
        manifest_path=manifest,
        node_executable="/path/that/must/not/be-invoked",
    )

    with pytest.raises(PrototypeSnapWorkerError) as error:
        await worker.attest_many(
            request_id="attest-many-too-large",
            evidence_jsons=["{}"] * 201,
        )

    assert error.value.code == "snap_worker_attestation_count_invalid"
    assert not invocations.exists()


@pytest.mark.asyncio
async def test_worker_refuses_oversized_request_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _bundle, invocations = _write_worker_fixture(tmp_path)
    worker = _worker(
        manifest_path=manifest,
        node_executable="/path/that/must/not/be-invoked",
    )
    monkeypatch.setattr(snap_worker_module, "_MAX_STDIN_BYTES", 32)

    with pytest.raises(PrototypeSnapWorkerError) as error:
        await worker.attest(
            request_id="attest-request-too-large",
            evidence_json="x" * 64,
        )

    assert error.value.code == "snap_worker_request_too_large"
    assert not invocations.exists()


@pytest.mark.asyncio
async def test_worker_refuses_bundle_changed_after_manifest_verification(
    tmp_path: Path,
) -> None:
    manifest, bundle, _invocations = _write_worker_fixture(tmp_path)
    worker = _worker(
        manifest_path=manifest,
        node_executable=_node_executable(),
    )
    bundle.write_bytes(bundle.read_bytes() + b"\n// changed after verification\n")

    with pytest.raises(PrototypeSnapWorkerError) as error:
        await worker.describe("describe-corrupt-bundle")

    assert error.value.code == "snap_worker_bundle_hash_mismatch"


def test_worker_refuses_a_tampered_source_manifest_hash(tmp_path: Path) -> None:
    manifest, _bundle, _invocations = _write_worker_fixture(tmp_path)
    raw: object = json.loads(manifest.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["snapSolverSourceHash"] = "sha256:" + "0" * 64
    manifest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(PrototypeSnapWorkerError) as error:
        _worker(
            manifest_path=manifest,
            node_executable=_node_executable(),
        )

    assert error.value.code == "snap_worker_manifest_invalid"


@pytest.mark.asyncio
async def test_worker_refuses_wrong_response_identity(tmp_path: Path) -> None:
    manifest, _bundle, _invocations = _write_worker_fixture(
        tmp_path,
        mode="wrong_identity",
    )
    worker = _worker(
        manifest_path=manifest,
        node_executable=_node_executable(),
    )

    with pytest.raises(PrototypeSnapWorkerError) as error:
        await worker.attest(request_id="attest-wrong-identity", evidence_json="{}")

    assert error.value.code == "snap_worker_identity_mismatch"


@pytest.mark.asyncio
async def test_worker_refuses_wrong_missing_or_reordered_evidence_hashes(
    tmp_path: Path,
) -> None:
    wrong_hash_dir = tmp_path / "wrong-hash"
    wrong_hash_dir.mkdir()
    wrong_hash_manifest, _bundle, _invocations = _write_worker_fixture(
        wrong_hash_dir,
        mode="wrong_hash",
    )
    wrong_hash_worker = _worker(
        manifest_path=wrong_hash_manifest,
        node_executable=_node_executable(),
    )

    with pytest.raises(PrototypeSnapWorkerError) as hash_error:
        await wrong_hash_worker.attest(
            request_id="attest-wrong-hash",
            evidence_json="{}",
        )

    assert hash_error.value.code == "snap_worker_evidence_hash_mismatch"

    count_dir = tmp_path / "count-mismatch"
    count_dir.mkdir()
    count_manifest, _bundle, _invocations = _write_worker_fixture(
        count_dir,
        mode="count_mismatch",
    )
    count_worker = _worker(
        manifest_path=count_manifest,
        node_executable=_node_executable(),
    )

    with pytest.raises(PrototypeSnapWorkerError) as count_error:
        await count_worker.attest_many(
            request_id="attest-count-mismatch",
            evidence_jsons=["{}", "[]"],
        )

    assert count_error.value.code == "snap_worker_attestation_count_mismatch"

    order_dir = tmp_path / "order-mismatch"
    order_dir.mkdir()
    order_manifest, _bundle, _invocations = _write_worker_fixture(
        order_dir,
        mode="reverse_hashes",
    )
    order_worker = _worker(
        manifest_path=order_manifest,
        node_executable=_node_executable(),
    )

    with pytest.raises(PrototypeSnapWorkerError) as order_error:
        await order_worker.attest_many(
            request_id="attest-order-mismatch",
            evidence_jsons=['{"sequence":1}', '{"sequence":2}'],
        )

    assert order_error.value.code == "snap_worker_evidence_hash_mismatch"


@pytest.mark.asyncio
async def test_worker_preserves_deterministic_attestation_mismatch_code(
    tmp_path: Path,
) -> None:
    manifest, _bundle, _invocations = _write_worker_fixture(
        tmp_path,
        mode="worker_error",
    )
    worker = _worker(
        manifest_path=manifest,
        node_executable=_node_executable(),
    )

    with pytest.raises(PrototypeSnapWorkerError) as error:
        await worker.attest(request_id="attest-mismatch", evidence_json="{}")

    assert error.value.code == "snap_attestation_mismatch"


@pytest.mark.asyncio
async def test_worker_uses_a_strict_success_response_boundary(tmp_path: Path) -> None:
    manifest, _bundle, _invocations = _write_worker_fixture(
        tmp_path,
        mode="unexpected_field",
    )
    worker = _worker(
        manifest_path=manifest,
        node_executable=_node_executable(),
    )

    with pytest.raises(PrototypeSnapWorkerError) as error:
        await worker.describe("describe-unexpected-field")

    assert error.value.code == "snap_worker_response_invalid"
