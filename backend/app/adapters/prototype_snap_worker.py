from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.structured_prototype import (
    PrototypeSnapWorkerAttestationResult,
    PrototypeSnapWorkerIdentity,
)

_SHA256_PREFIX = "sha256:"
_MAX_MANIFEST_BYTES = 128 * 1024
_MAX_STDOUT_BYTES = 8 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_MAX_STDIN_BYTES = 32 * 1024 * 1024
_MAX_ATTESTATIONS = 200


class PrototypeSnapWorkerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ManifestSource(_StrictModel):
    path: str = Field(min_length=1)
    content_hash: str = Field(alias="hash")
    byte_size: int = Field(alias="byteSize", ge=0)


class _WorkerManifest(_StrictModel):
    manifest_version: Literal["prototype-snap-worker-manifest/v1"] = Field(alias="manifestVersion")
    protocol_version: Literal["prototype-snap-worker/v1"] = Field(alias="protocolVersion")
    snap_solver_version: str = Field(alias="snapSolverVersion", min_length=1)
    snap_solver_source_hash: str = Field(alias="snapSolverSourceHash")
    bundle_file: str = Field(alias="bundleFile", min_length=1)
    bundle_hash: str = Field(alias="bundleHash")
    bundle_byte_size: int = Field(alias="bundleByteSize", gt=0)
    build_tool: str = Field(alias="buildTool", min_length=1)
    target: Literal["node20"]
    sources: list[_ManifestSource] = Field(min_length=1)


class _ResponseHeader(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: str
    status: Literal["ok", "error"]
    snap_solver_version: str = Field(alias="snapSolverVersion")
    snap_solver_source_hash: str = Field(alias="snapSolverSourceHash")


class _SuccessResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    status: Literal["ok"]
    snap_solver_version: str = Field(alias="snapSolverVersion")
    snap_solver_source_hash: str = Field(alias="snapSolverSourceHash")


class _WorkerIdentityResult(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    snap_solver_version: str = Field(alias="snapSolverVersion")
    snap_solver_source_hash: str = Field(alias="snapSolverSourceHash")


class _AttestationResult(_StrictModel):
    evidence_hash: str = Field(alias="evidenceHash")


class _AttestationBatchResult(_StrictModel):
    evidence_hashes: list[str] = Field(alias="evidenceHashes", max_length=_MAX_ATTESTATIONS)


class _DescribeResponse(_SuccessResponse):
    action: Literal["describe"]
    result: _WorkerIdentityResult


class _AttestResponse(_SuccessResponse):
    action: Literal["attest"]
    result: _AttestationResult


class _AttestManyResponse(_SuccessResponse):
    action: Literal["attestMany"]
    result: _AttestationBatchResult


class _WorkerErrorDetail(_StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class _WorkerErrorResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: str
    status: Literal["error"]
    snap_solver_version: str = Field(alias="snapSolverVersion")
    snap_solver_source_hash: str = Field(alias="snapSolverSourceHash")
    error: _WorkerErrorDetail


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


def _sha256(value: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _is_sha256(value: str) -> bool:
    if len(value) != 71 or not value.startswith(_SHA256_PREFIX):
        return False
    try:
        int(value[len(_SHA256_PREFIX) :], 16)
    except ValueError:
        return False
    return True


def _require_response_hash(value: str, field: str) -> None:
    if not _is_sha256(value):
        raise PrototypeSnapWorkerError(
            "snap_worker_response_invalid",
            f"prototype snap worker returned an invalid hash: {field}",
        )


class PrototypeSnapWorker:
    def __init__(
        self,
        *,
        attest_timeout_s: float,
        attest_many_timeout_s: float,
        manifest_path: Path | None = None,
        node_executable: str | None = None,
    ) -> None:
        if attest_timeout_s <= 0:
            raise ValueError("prototype snap worker attest timeout must be positive")
        if attest_many_timeout_s <= 0:
            raise ValueError("prototype snap worker attestMany timeout must be positive")
        default_manifest = (
            Path(__file__).resolve().parent.parent
            / "runtime_assets"
            / "prototype_snap_worker.manifest.json"
        )
        self.manifest_path = (manifest_path or default_manifest).resolve()
        self.attest_timeout_s = attest_timeout_s
        self.attest_many_timeout_s = attest_many_timeout_s
        self._manifest = self._load_manifest()
        self.bundle_path = self._resolve_bundle_path(self._manifest)
        self.node_executable = node_executable or shutil.which("node") or ""
        if not self.node_executable:
            raise PrototypeSnapWorkerError(
                "snap_worker_node_missing",
                "Node.js is required for the prototype snap worker",
            )
        self.identity = PrototypeSnapWorkerIdentity(
            protocol_version=self._manifest.protocol_version,
            snap_solver_version=self._manifest.snap_solver_version,
            snap_solver_source_hash=self._manifest.snap_solver_source_hash,
            snap_solver_bundle_hash=self._manifest.bundle_hash,
            snap_solver_bundle_byte_size=self._manifest.bundle_byte_size,
            build_tool=self._manifest.build_tool,
            target=self._manifest.target,
        )
        self._verify_bundle()

    async def describe(self, request_id: str) -> PrototypeSnapWorkerIdentity:
        response = await self._execute(
            action="describe",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "describe",
            },
            response_model=_DescribeResponse,
            timeout_s=self.attest_timeout_s,
        )
        result = response.result
        if (
            result.protocol_version != self.identity.protocol_version
            or result.snap_solver_version != self.identity.snap_solver_version
            or result.snap_solver_source_hash != self.identity.snap_solver_source_hash
        ):
            raise PrototypeSnapWorkerError(
                "snap_worker_identity_mismatch",
                "prototype snap worker describe result does not match its manifest",
            )
        return self.identity

    async def attest(
        self,
        *,
        request_id: str,
        evidence_json: str,
    ) -> PrototypeSnapWorkerAttestationResult:
        response = await self._execute(
            action="attest",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "attest",
                "evidenceJson": evidence_json,
            },
            response_model=_AttestResponse,
            timeout_s=self.attest_timeout_s,
        )
        return self._attestation_result(response.result.evidence_hash, evidence_json)

    async def attest_many(
        self,
        *,
        request_id: str,
        evidence_jsons: list[str],
    ) -> tuple[PrototypeSnapWorkerAttestationResult, ...]:
        if not evidence_jsons or len(evidence_jsons) > _MAX_ATTESTATIONS:
            raise PrototypeSnapWorkerError(
                "snap_worker_attestation_count_invalid",
                "prototype snap worker attestMany requires between 1 and 200 entries",
            )
        response = await self._execute(
            action="attestMany",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "attestMany",
                "evidenceJsons": evidence_jsons,
            },
            response_model=_AttestManyResponse,
            timeout_s=self.attest_many_timeout_s,
        )
        if len(response.result.evidence_hashes) != len(evidence_jsons):
            raise PrototypeSnapWorkerError(
                "snap_worker_attestation_count_mismatch",
                "prototype snap worker returned the wrong number of attestations",
            )
        return tuple(
            self._attestation_result(
                evidence_hash,
                evidence_json,
            )
            for evidence_hash, evidence_json in zip(
                response.result.evidence_hashes,
                evidence_jsons,
                strict=True,
            )
        )

    def _load_manifest(self) -> _WorkerManifest:
        try:
            raw = self.manifest_path.read_bytes()
        except OSError as exc:
            raise PrototypeSnapWorkerError(
                "snap_worker_manifest_missing",
                "prototype snap worker manifest is unavailable",
            ) from exc
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise PrototypeSnapWorkerError(
                "snap_worker_manifest_invalid",
                "prototype snap worker manifest exceeds 128 KiB",
            )
        try:
            manifest = _WorkerManifest.model_validate_json(raw, strict=True)
        except ValidationError as exc:
            raise PrototypeSnapWorkerError(
                "snap_worker_manifest_invalid",
                "prototype snap worker manifest is invalid",
            ) from exc
        manifest_hashes = (
            (manifest.snap_solver_source_hash, "snapSolverSourceHash"),
            (manifest.bundle_hash, "bundleHash"),
            *((source.content_hash, f"sources[{source.path}].hash") for source in manifest.sources),
        )
        if any(not _is_sha256(value) for value, _field in manifest_hashes):
            raise PrototypeSnapWorkerError(
                "snap_worker_manifest_invalid",
                "prototype snap worker manifest contains an invalid hash",
            )
        source_paths = [source.path for source in manifest.sources]
        if len(source_paths) != len(set(source_paths)):
            raise PrototypeSnapWorkerError(
                "snap_worker_manifest_invalid",
                "prototype snap worker manifest contains duplicate source paths",
            )
        source_payload = [
            {
                "path": source.path,
                "hash": source.content_hash,
                "byteSize": source.byte_size,
            }
            for source in manifest.sources
        ]
        encoded_sources = json.dumps(
            source_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if _sha256(encoded_sources) != manifest.snap_solver_source_hash:
            raise PrototypeSnapWorkerError(
                "snap_worker_manifest_invalid",
                "prototype snap worker source manifest hash does not match",
            )
        return manifest

    def _resolve_bundle_path(self, manifest: _WorkerManifest) -> Path:
        manifest_directory = self.manifest_path.parent.resolve()
        unresolved_bundle_path = manifest_directory / manifest.bundle_file
        if unresolved_bundle_path.is_symlink():
            raise PrototypeSnapWorkerError(
                "snap_worker_bundle_invalid",
                "prototype snap worker bundle must not be a symlink",
            )
        bundle_path = unresolved_bundle_path.resolve()
        try:
            bundle_path.relative_to(manifest_directory)
        except ValueError as exc:
            raise PrototypeSnapWorkerError(
                "snap_worker_bundle_invalid",
                "prototype snap worker bundle path escapes its manifest directory",
            ) from exc
        return bundle_path

    def _verify_bundle(self) -> None:
        try:
            bundle = self.bundle_path.read_bytes()
        except OSError as exc:
            raise PrototypeSnapWorkerError(
                "snap_worker_bundle_missing",
                "prototype snap worker bundle is unavailable",
            ) from exc
        if (
            len(bundle) != self._manifest.bundle_byte_size
            or _sha256(bundle) != self._manifest.bundle_hash
        ):
            raise PrototypeSnapWorkerError(
                "snap_worker_bundle_hash_mismatch",
                "prototype snap worker bundle does not match its manifest",
            )

    async def _execute(
        self,
        *,
        action: Literal["describe", "attest", "attestMany"],
        request: dict[str, object],
        response_model: type[ResponseModel],
        timeout_s: float,
    ) -> ResponseModel:
        self._verify_bundle()
        request_id_value = request["requestId"]
        if not isinstance(request_id_value, str) or not request_id_value:
            raise ValueError("prototype snap worker request id must not be empty")
        request_bytes = json.dumps(
            request,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(request_bytes) > _MAX_STDIN_BYTES:
            raise PrototypeSnapWorkerError(
                "snap_worker_request_too_large",
                "prototype snap worker request exceeds 32 MiB",
            )
        try:
            process = await asyncio.create_subprocess_exec(
                self.node_executable,
                "--max-old-space-size=256",
                str(self.bundle_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise PrototypeSnapWorkerError(
                "snap_worker_spawn_failed",
                "prototype snap worker process could not start",
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(request_bytes),
                timeout=timeout_s,
            )
        except TimeoutError as exc:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
            raise PrototypeSnapWorkerError(
                "snap_worker_timeout",
                "prototype snap worker exceeded its execution deadline",
            ) from exc
        if len(stdout) > _MAX_STDOUT_BYTES or len(stderr) > _MAX_STDERR_BYTES:
            raise PrototypeSnapWorkerError(
                "snap_worker_output_too_large",
                "prototype snap worker output exceeded its bounded protocol",
            )
        try:
            header = _ResponseHeader.model_validate_json(stdout, strict=True)
        except ValidationError as exc:
            raise PrototypeSnapWorkerError(
                "snap_worker_response_invalid",
                "prototype snap worker returned an invalid response envelope",
            ) from exc
        self._validate_response_identity(header, request_id_value, action)
        if header.status == "error":
            try:
                error_response = _WorkerErrorResponse.model_validate_json(stdout, strict=True)
            except ValidationError as exc:
                raise PrototypeSnapWorkerError(
                    "snap_worker_response_invalid",
                    "prototype snap worker returned an invalid error response",
                ) from exc
            raise PrototypeSnapWorkerError(
                error_response.error.code,
                error_response.error.message,
            )
        if process.returncode != 0:
            raise PrototypeSnapWorkerError(
                "snap_worker_process_failed",
                "prototype snap worker exited unsuccessfully",
            )
        if stderr:
            raise PrototypeSnapWorkerError(
                "snap_worker_stderr_unexpected",
                "prototype snap worker wrote unexpected stderr output",
            )
        try:
            return response_model.model_validate_json(stdout, strict=True)
        except ValidationError as exc:
            raise PrototypeSnapWorkerError(
                "snap_worker_response_invalid",
                "prototype snap worker returned an invalid success response",
            ) from exc

    def _validate_response_identity(
        self,
        response: _ResponseHeader,
        request_id: str,
        action: str,
    ) -> None:
        if (
            response.request_id != request_id
            or response.action != action
            or response.protocol_version != self.identity.protocol_version
            or response.snap_solver_version != self.identity.snap_solver_version
            or response.snap_solver_source_hash != self.identity.snap_solver_source_hash
        ):
            raise PrototypeSnapWorkerError(
                "snap_worker_identity_mismatch",
                "prototype snap worker response identity does not match its request and manifest",
            )

    @staticmethod
    def _attestation_result(
        evidence_hash: str,
        evidence_json: str,
    ) -> PrototypeSnapWorkerAttestationResult:
        _require_response_hash(evidence_hash, "evidenceHash")
        if evidence_hash != _sha256(evidence_json.encode("utf-8")):
            raise PrototypeSnapWorkerError(
                "snap_worker_evidence_hash_mismatch",
                "prototype snap worker evidence hash does not match its canonical input",
            )
        return PrototypeSnapWorkerAttestationResult(evidence_hash=evidence_hash)
