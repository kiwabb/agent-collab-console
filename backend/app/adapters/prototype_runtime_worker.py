from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.structured_prototype import (
    PrototypeRuntimeTransitionOutcome,
    PrototypeRuntimeWorkerIdentity,
    PrototypeRuntimeWorkerReplayResult,
    PrototypeRuntimeWorkerStateResult,
    PrototypeRuntimeWorkerTransitionResult,
)

_SHA256_PREFIX = "sha256:"
_MAX_MANIFEST_BYTES = 128 * 1024
_MAX_STDOUT_BYTES = 8 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_DEFAULT_TIMEOUT_S = 5.0

logger = logging.getLogger(__name__)


class PrototypeRuntimeWorkerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ManifestSource(_StrictModel):
    path: str
    content_hash: str = Field(alias="hash")
    byte_size: int = Field(alias="byteSize", ge=0)


class _WorkerManifest(_StrictModel):
    manifest_version: Literal["prototype-runtime-worker-manifest/v1"] = Field(
        alias="manifestVersion"
    )
    protocol_version: Literal["prototype-runtime-worker/v1"] = Field(alias="protocolVersion")
    runtime_core_version: str = Field(alias="runtimeCoreVersion", min_length=1)
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion", min_length=1)
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
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")


class _WorkerErrorDetail(_StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class _WorkerErrorResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: str
    status: Literal["error"]
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    error: _WorkerErrorDetail


class _WorkerIdentityResult(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")


class _WorkerStateResult(_StrictModel):
    state_json: str = Field(alias="stateJson", min_length=2)
    state_hash: str = Field(alias="stateHash")
    view_model_json: str = Field(alias="viewModelJson", min_length=2)
    view_model_hash: str = Field(alias="viewModelHash")


class _EffectEvidence(_StrictModel):
    event_index: int = Field(alias="eventIndex", ge=0)
    effect_index: int = Field(alias="effectIndex", ge=0)
    effect_kind: Literal[
        "setVariable",
        "validateForm",
        "createEntity",
        "updateEntity",
        "navigate",
        "notify",
    ] = Field(alias="effectKind")
    before_state_hash: str = Field(alias="beforeStateHash")
    after_state_hash: str = Field(alias="afterStateHash")


class _TransitionReport(_StrictModel):
    client_event_id: str = Field(alias="clientEventId", min_length=1)
    base_sequence_no: int = Field(alias="baseSequenceNo", ge=0)
    result_sequence_no: int = Field(alias="resultSequenceNo", gt=0)
    outcome: PrototypeRuntimeTransitionOutcome
    matched_rule_ids: list[str] = Field(alias="matchedRuleIds")
    base_state_hash: str = Field(alias="baseStateHash")
    result_state_hash: str = Field(alias="resultStateHash")
    result_view_model_hash: str = Field(alias="resultViewModelHash")
    effects: list[_EffectEvidence]


class _WorkerTransitionResult(_WorkerStateResult):
    events_json: str = Field(alias="eventsJson", min_length=2)
    event_batch_json: str = Field(alias="eventBatchJson", min_length=2)
    event_batch_hash: str = Field(alias="eventBatchHash")
    matched_rule_ids_json: str = Field(alias="matchedRuleIdsJson", min_length=2)
    guard_report_json: str = Field(alias="guardReportJson", min_length=2)
    guard_report_hash: str = Field(alias="guardReportHash")
    effect_report_json: str = Field(alias="effectReportJson", min_length=2)
    effect_report_hash: str = Field(alias="effectReportHash")
    report: _TransitionReport


class _WorkerReplayResult(_StrictModel):
    transitions: list[_WorkerTransitionResult]
    final: _WorkerStateResult


class _DescribeResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: Literal["describe"]
    status: Literal["ok"]
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    result: _WorkerIdentityResult


class _InitializeResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: Literal["initialize"]
    status: Literal["ok"]
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    result: _WorkerStateResult


class _ApplyResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: Literal["apply"]
    status: Literal["ok"]
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    result: _WorkerTransitionResult


class _ReplayResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: Literal["replay"]
    status: Literal["ok"]
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    result: _WorkerReplayResult


class _GuardReport(_StrictModel):
    matched_rule_ids: list[str] = Field(alias="matchedRuleIds")
    outcome: PrototypeRuntimeTransitionOutcome


class _EffectReport(_StrictModel):
    effects: list[_EffectEvidence]


class _EventBatchEvidence(_StrictModel):
    client_event_id: str = Field(alias="clientEventId", min_length=1)
    expected_sequence_no: int = Field(alias="expectedSequenceNo", ge=0)
    events: list[object] = Field(min_length=1, max_length=20)


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


def _sha256(value: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _require_hash(value: str, field: str) -> None:
    if len(value) != 71 or not value.startswith(_SHA256_PREFIX):
        raise PrototypeRuntimeWorkerError(
            "runtime_worker_response_invalid",
            f"prototype runtime worker returned an invalid hash: {field}",
        )
    try:
        int(value[len(_SHA256_PREFIX) :], 16)
    except ValueError as exc:
        raise PrototypeRuntimeWorkerError(
            "runtime_worker_response_invalid",
            f"prototype runtime worker returned an invalid hash: {field}",
        ) from exc


def _validated_json_model[Model: BaseModel](
    model: type[Model],
    value: str,
    field: str,
) -> Model:
    try:
        return model.model_validate_json(value, strict=True)
    except ValidationError as exc:
        raise PrototypeRuntimeWorkerError(
            "runtime_worker_response_invalid",
            f"prototype runtime worker returned invalid canonical JSON: {field}",
        ) from exc


class PrototypeRuntimeWorker:
    def __init__(
        self,
        *,
        manifest_path: Path | None = None,
        node_executable: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("prototype runtime worker timeout must be positive")
        default_manifest = (
            Path(__file__).resolve().parent.parent
            / "runtime_assets"
            / "prototype_runtime_worker.manifest.json"
        )
        self.manifest_path = (manifest_path or default_manifest).resolve()
        self.timeout_s = timeout_s
        self._manifest = self._load_manifest()
        self.bundle_path = self._resolve_bundle_path(self._manifest)
        self.node_executable = node_executable or shutil.which("node") or ""
        if not self.node_executable:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_node_missing",
                "Node.js is required for the prototype runtime worker",
            )
        self.identity = PrototypeRuntimeWorkerIdentity(
            protocol_version=self._manifest.protocol_version,
            runtime_core_version=self._manifest.runtime_core_version,
            runtime_core_source_hash=self._manifest.runtime_core_source_hash,
            runtime_core_bundle_hash=self._manifest.bundle_hash,
            runtime_core_bundle_byte_size=self._manifest.bundle_byte_size,
            state_machine_kernel_version=self._manifest.state_machine_kernel_version,
            build_tool=self._manifest.build_tool,
            target=self._manifest.target,
        )
        self._verify_bundle()

    async def describe(self, request_id: str) -> PrototypeRuntimeWorkerIdentity:
        response = await self._execute(
            action="describe",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "describe",
            },
            response_model=_DescribeResponse,
        )
        result = response.result
        if (
            result.protocol_version != self.identity.protocol_version
            or result.runtime_core_version != self.identity.runtime_core_version
            or result.runtime_core_source_hash != self.identity.runtime_core_source_hash
            or result.state_machine_kernel_version != self.identity.state_machine_kernel_version
        ):
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_identity_mismatch",
                "prototype runtime worker describe result does not match its manifest",
            )
        return self.identity

    async def initialize_state(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        scenario_id: str,
        session_id: str,
    ) -> PrototypeRuntimeWorkerStateResult:
        response = await self._execute(
            action="initialize",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "initialize",
                "definition": definition,
                "scenarioId": scenario_id,
                "sessionId": session_id,
            },
            response_model=_InitializeResponse,
        )
        return self._state_result(response.result)

    async def apply_event_batch(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        state_json: str,
        batch: dict[str, object],
    ) -> PrototypeRuntimeWorkerTransitionResult:
        response = await self._execute(
            action="apply",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "apply",
                "definition": definition,
                "stateJson": state_json,
                "batch": batch,
            },
            response_model=_ApplyResponse,
        )
        transition = self._transition_record(response.result)
        if response.result.report.base_state_hash != _sha256(state_json.encode("utf-8")):
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_base_state_hash_mismatch",
                "prototype runtime worker transition base hash does not match its input state",
            )
        return transition

    async def replay_event_batches(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        state_json: str,
        batches: list[dict[str, object]],
    ) -> PrototypeRuntimeWorkerReplayResult:
        response = await self._execute(
            action="replay",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "replay",
                "definition": definition,
                "stateJson": state_json,
                "batches": batches,
            },
            response_model=_ReplayResponse,
        )
        transitions: list[PrototypeRuntimeWorkerTransitionResult] = []
        expected_state_hash = _sha256(state_json.encode("utf-8"))
        for model in response.result.transitions:
            transition = self._transition_record(model)
            if model.report.base_state_hash != expected_state_hash:
                raise PrototypeRuntimeWorkerError(
                    "runtime_worker_replay_hash_mismatch",
                    "prototype runtime worker replay transition does not match the prior state",
                )
            transitions.append(transition)
            expected_state_hash = model.state_hash
        final = self._state_result(response.result.final)
        if final.state_hash != expected_state_hash:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_replay_hash_mismatch",
                "prototype runtime worker replay final state does not match its transitions",
            )
        return PrototypeRuntimeWorkerReplayResult(
            transitions=tuple(transitions),
            final=final,
        )

    def _load_manifest(self) -> _WorkerManifest:
        try:
            raw = self.manifest_path.read_bytes()
        except OSError as exc:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_manifest_missing",
                "prototype runtime worker manifest is unavailable",
            ) from exc
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_manifest_invalid",
                "prototype runtime worker manifest exceeds 128 KiB",
            )
        try:
            manifest = _WorkerManifest.model_validate_json(raw, strict=True)
        except ValidationError as exc:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_manifest_invalid",
                "prototype runtime worker manifest is invalid",
            ) from exc
        for value, field in (
            (manifest.runtime_core_source_hash, "runtimeCoreSourceHash"),
            (manifest.bundle_hash, "bundleHash"),
        ):
            _require_hash(value, field)
        source_payload = [
            {
                "path": source.path,
                "hash": source.content_hash,
                "byteSize": source.byte_size,
            }
            for source in manifest.sources
        ]
        for source in manifest.sources:
            _require_hash(source.content_hash, f"sources[{source.path}].hash")
        encoded_sources = json.dumps(
            source_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if _sha256(encoded_sources) != manifest.runtime_core_source_hash:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_manifest_invalid",
                "prototype runtime worker source manifest hash does not match",
            )
        return manifest

    def _resolve_bundle_path(self, manifest: _WorkerManifest) -> Path:
        manifest_directory = self.manifest_path.parent.resolve()
        unresolved_bundle_path = manifest_directory / manifest.bundle_file
        if unresolved_bundle_path.is_symlink():
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_bundle_invalid",
                "prototype runtime worker bundle must not be a symlink",
            )
        bundle_path = unresolved_bundle_path.resolve()
        try:
            bundle_path.relative_to(manifest_directory)
        except ValueError as exc:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_bundle_invalid",
                "prototype runtime worker bundle path escapes its manifest directory",
            ) from exc
        return bundle_path

    def _verify_bundle(self) -> None:
        try:
            bundle = self.bundle_path.read_bytes()
        except OSError as exc:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_bundle_missing",
                "prototype runtime worker bundle is unavailable",
            ) from exc
        if (
            len(bundle) != self._manifest.bundle_byte_size
            or _sha256(bundle) != self._manifest.bundle_hash
        ):
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_bundle_hash_mismatch",
                "prototype runtime worker bundle does not match its manifest",
            )

    async def _execute(
        self,
        *,
        action: Literal["describe", "initialize", "apply", "replay"],
        request: dict[str, object],
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        self._verify_bundle()
        started_at = time.monotonic()
        request_id_value = request["requestId"]
        if not isinstance(request_id_value, str) or not request_id_value:
            raise ValueError("prototype runtime worker request id must not be empty")
        request_bytes = json.dumps(
            request,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        try:
            process = await asyncio.create_subprocess_exec(
                self.node_executable,
                "--max-old-space-size=128",
                str(self.bundle_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_spawn_failed",
                "prototype runtime worker process could not start",
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(request_bytes),
                timeout=self.timeout_s,
            )
        except TimeoutError as exc:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            logger.error(
                "prototype runtime worker timed out: action=%s request_id=%s "
                "timeout_s=%.3f elapsed_ms=%d",
                action,
                request_id_value,
                self.timeout_s,
                elapsed_ms,
            )
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_timeout",
                "prototype runtime worker exceeded its execution deadline",
            ) from exc
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            "prototype runtime worker process exited: action=%s request_id=%s "
            "timeout_s=%.3f elapsed_ms=%d",
            action,
            request_id_value,
            self.timeout_s,
            elapsed_ms,
        )
        if len(stdout) > _MAX_STDOUT_BYTES or len(stderr) > _MAX_STDERR_BYTES:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_output_too_large",
                "prototype runtime worker output exceeded its bounded protocol",
            )
        try:
            header = _ResponseHeader.model_validate_json(stdout, strict=True)
        except ValidationError as exc:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_response_invalid",
                "prototype runtime worker returned an invalid response envelope",
            ) from exc
        self._validate_response_identity(header, request_id_value, action)
        if header.status == "error":
            try:
                error_response = _WorkerErrorResponse.model_validate_json(stdout, strict=True)
            except ValidationError as exc:
                raise PrototypeRuntimeWorkerError(
                    "runtime_worker_response_invalid",
                    "prototype runtime worker returned an invalid error response",
                ) from exc
            raise PrototypeRuntimeWorkerError(
                error_response.error.code,
                error_response.error.message,
            )
        if process.returncode != 0:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_process_failed",
                "prototype runtime worker exited unsuccessfully",
            )
        if stderr:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_stderr_unexpected",
                "prototype runtime worker wrote unexpected stderr output",
            )
        try:
            return response_model.model_validate_json(stdout, strict=True)
        except ValidationError as exc:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_response_invalid",
                "prototype runtime worker returned an invalid success response",
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
            or response.runtime_core_version != self.identity.runtime_core_version
            or response.runtime_core_source_hash != self.identity.runtime_core_source_hash
            or response.state_machine_kernel_version != self.identity.state_machine_kernel_version
        ):
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_identity_mismatch",
                "prototype runtime worker response identity does not match its request and manifest",
            )

    @staticmethod
    def _state_result(model: _WorkerStateResult) -> PrototypeRuntimeWorkerStateResult:
        for value, field in (
            (model.state_hash, "stateHash"),
            (model.view_model_hash, "viewModelHash"),
        ):
            _require_hash(value, field)
        if _sha256(model.state_json.encode("utf-8")) != model.state_hash:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_state_hash_mismatch",
                "prototype runtime worker state JSON does not match its hash",
            )
        if _sha256(model.view_model_json.encode("utf-8")) != model.view_model_hash:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_view_model_hash_mismatch",
                "prototype runtime worker view-model JSON does not match its hash",
            )
        return PrototypeRuntimeWorkerStateResult(
            state_json=model.state_json,
            state_hash=model.state_hash,
            view_model_json=model.view_model_json,
            view_model_hash=model.view_model_hash,
        )

    @staticmethod
    def _transition_result(model: _WorkerTransitionResult) -> _WorkerTransitionResult:
        PrototypeRuntimeWorker._state_result(model)
        for value, field in (
            (model.event_batch_hash, "eventBatchHash"),
            (model.guard_report_hash, "guardReportHash"),
            (model.effect_report_hash, "effectReportHash"),
            (model.report.base_state_hash, "report.baseStateHash"),
            (model.report.result_state_hash, "report.resultStateHash"),
            (model.report.result_view_model_hash, "report.resultViewModelHash"),
        ):
            _require_hash(value, field)
        if _sha256(model.event_batch_json.encode("utf-8")) != model.event_batch_hash:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_event_batch_hash_mismatch",
                "prototype runtime worker event batch JSON does not match its hash",
            )
        if _sha256(model.guard_report_json.encode("utf-8")) != model.guard_report_hash:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_guard_report_hash_mismatch",
                "prototype runtime worker guard report JSON does not match its hash",
            )
        if _sha256(model.effect_report_json.encode("utf-8")) != model.effect_report_hash:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_effect_report_hash_mismatch",
                "prototype runtime worker effect report JSON does not match its hash",
            )
        guard_report = _validated_json_model(
            _GuardReport,
            model.guard_report_json,
            "guardReportJson",
        )
        effect_report = _validated_json_model(
            _EffectReport,
            model.effect_report_json,
            "effectReportJson",
        )
        event_batch = _validated_json_model(
            _EventBatchEvidence,
            model.event_batch_json,
            "eventBatchJson",
        )
        try:
            matched_rule_ids: object = json.loads(model.matched_rule_ids_json)
            events: object = json.loads(model.events_json)
        except json.JSONDecodeError as exc:
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_response_invalid",
                "prototype runtime worker returned invalid event evidence JSON",
            ) from exc
        if (
            not isinstance(matched_rule_ids, list)
            or any(not isinstance(item, str) for item in matched_rule_ids)
            or matched_rule_ids != model.report.matched_rule_ids
            or guard_report.matched_rule_ids != model.report.matched_rule_ids
            or guard_report.outcome != model.report.outcome
            or effect_report.effects != model.report.effects
            or not isinstance(events, list)
            or events != event_batch.events
            or event_batch.client_event_id != model.report.client_event_id
            or event_batch.expected_sequence_no != model.report.base_sequence_no
            or model.report.result_sequence_no != model.report.base_sequence_no + 1
            or model.state_hash != model.report.result_state_hash
            or model.view_model_hash != model.report.result_view_model_hash
        ):
            raise PrototypeRuntimeWorkerError(
                "runtime_worker_transition_evidence_mismatch",
                "prototype runtime worker transition evidence is internally inconsistent",
            )
        return model

    @staticmethod
    def _transition_record(
        model: _WorkerTransitionResult,
    ) -> PrototypeRuntimeWorkerTransitionResult:
        PrototypeRuntimeWorker._transition_result(model)
        report = model.report
        return PrototypeRuntimeWorkerTransitionResult(
            client_event_id=report.client_event_id,
            base_sequence_no=report.base_sequence_no,
            result_sequence_no=report.result_sequence_no,
            outcome=report.outcome,
            state_json=model.state_json,
            state_hash=model.state_hash,
            view_model_json=model.view_model_json,
            view_model_hash=model.view_model_hash,
            events_json=model.events_json,
            event_batch_json=model.event_batch_json,
            event_batch_hash=model.event_batch_hash,
            matched_rule_ids_json=model.matched_rule_ids_json,
            guard_report_json=model.guard_report_json,
            guard_report_hash=model.guard_report_hash,
            effect_report_json=model.effect_report_json,
            effect_report_hash=model.effect_report_hash,
        )
