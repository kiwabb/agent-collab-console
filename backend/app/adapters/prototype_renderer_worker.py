from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.prototype_object_store import canonical_json_bytes
from app.domain.structured_prototype import (
    PrototypeRenderedFile,
    PrototypeRendererWorkerIdentity,
    PrototypeRendererWorkerResult,
)

_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_STDOUT_BYTES = 16 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_DEFAULT_TIMEOUT_S = 10.0
_ALLOWED_FILES = ("document.json", "index.html", "runtime.js", "styles.css")


class PrototypeRendererWorkerError(RuntimeError):
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
    manifest_version: Literal["prototype-renderer-worker-manifest/v1"] = Field(
        alias="manifestVersion"
    )
    protocol_version: Literal["prototype-renderer-worker/v1"] = Field(alias="protocolVersion")
    renderer_version: str = Field(alias="rendererVersion", min_length=1)
    renderer_environment_version: str = Field(
        alias="rendererEnvironmentVersion", min_length=1
    )
    renderer_source_hash: str = Field(alias="rendererSourceHash")
    runtime_core_version: str = Field(alias="runtimeCoreVersion", min_length=1)
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    runtime_core_bundle_hash: str = Field(alias="runtimeCoreBundleHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion", min_length=1)
    render_runtime_image_hash: str = Field(alias="renderRuntimeImageHash")
    browser_version: str = Field(alias="browserVersion", min_length=1)
    font_pack_hash: str = Field(alias="fontPackHash")
    viewport_profile_hash: str = Field(alias="viewportProfileHash")
    sandbox_policy_version: str = Field(alias="sandboxPolicyVersion", min_length=1)
    public_runtime_file: str = Field(alias="publicRuntimeFile", min_length=1)
    public_runtime_hash: str = Field(alias="publicRuntimeHash")
    public_runtime_byte_size: int = Field(alias="publicRuntimeByteSize", gt=0)
    bundle_file: str = Field(alias="bundleFile", min_length=1)
    bundle_hash: str = Field(alias="bundleHash")
    bundle_byte_size: int = Field(alias="bundleByteSize", gt=0)
    build_tool: str = Field(alias="buildTool", min_length=1)
    target: Literal["node20"]
    sources: list[_ManifestSource] = Field(min_length=1)


class _ResponseIdentity(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: str
    status: Literal["ok", "error"]
    renderer_version: str = Field(alias="rendererVersion")
    renderer_environment_version: str = Field(alias="rendererEnvironmentVersion")
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    runtime_core_bundle_hash: str = Field(alias="runtimeCoreBundleHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    render_runtime_image_hash: str = Field(alias="renderRuntimeImageHash")
    browser_version: str = Field(alias="browserVersion")
    font_pack_hash: str = Field(alias="fontPackHash")
    viewport_profile_hash: str = Field(alias="viewportProfileHash")
    sandbox_policy_version: str = Field(alias="sandboxPolicyVersion")


class _IdentityResult(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    renderer_version: str = Field(alias="rendererVersion")
    renderer_environment_version: str = Field(alias="rendererEnvironmentVersion")
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    runtime_core_bundle_hash: str = Field(alias="runtimeCoreBundleHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    render_runtime_image_hash: str = Field(alias="renderRuntimeImageHash")
    browser_version: str = Field(alias="browserVersion")
    font_pack_hash: str = Field(alias="fontPackHash")
    viewport_profile_hash: str = Field(alias="viewportProfileHash")
    sandbox_policy_version: str = Field(alias="sandboxPolicyVersion")


class _SuccessResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    status: Literal["ok"]
    renderer_version: str = Field(alias="rendererVersion")
    renderer_environment_version: str = Field(alias="rendererEnvironmentVersion")
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    runtime_core_bundle_hash: str = Field(alias="runtimeCoreBundleHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    render_runtime_image_hash: str = Field(alias="renderRuntimeImageHash")
    browser_version: str = Field(alias="browserVersion")
    font_pack_hash: str = Field(alias="fontPackHash")
    viewport_profile_hash: str = Field(alias="viewportProfileHash")
    sandbox_policy_version: str = Field(alias="sandboxPolicyVersion")


class _DescribeResponse(_SuccessResponse):
    action: Literal["describe"]
    result: _IdentityResult


class _WorkerErrorDetail(_StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class _WorkerErrorResponse(_StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    action: str
    status: Literal["error"]
    renderer_version: str = Field(alias="rendererVersion")
    renderer_environment_version: str = Field(alias="rendererEnvironmentVersion")
    runtime_core_version: str = Field(alias="runtimeCoreVersion")
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    runtime_core_bundle_hash: str = Field(alias="runtimeCoreBundleHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion")
    render_runtime_image_hash: str = Field(alias="renderRuntimeImageHash")
    browser_version: str = Field(alias="browserVersion")
    font_pack_hash: str = Field(alias="fontPackHash")
    viewport_profile_hash: str = Field(alias="viewportProfileHash")
    sandbox_policy_version: str = Field(alias="sandboxPolicyVersion")
    error: _WorkerErrorDetail


class _OutputFileDescriptor(_StrictModel):
    relative_path: str = Field(alias="relativePath", min_length=1)
    byte_size: int = Field(alias="byteSize", ge=0)
    content_hash: str = Field(alias="contentHash")


class _OutputFile(_OutputFileDescriptor):
    content_base64: str = Field(alias="contentBase64")


class _PreflightCheck(_StrictModel):
    code: str = Field(min_length=1)
    status: Literal["passed"]
    evidence: str = Field(min_length=1)


class _PreflightReport(_StrictModel):
    contract_version: Literal[1] = Field(alias="contractVersion")
    checks: list[_PreflightCheck] = Field(min_length=1)
    page_count: int = Field(alias="pageCount", gt=0)
    node_count: int = Field(alias="nodeCount", gt=0)
    form_binding_count: int = Field(alias="formBindingCount", ge=0)
    external_asset_count: int = Field(alias="externalAssetCount", ge=0)


class _OutputManifest(_StrictModel):
    contract_version: Literal[1] = Field(alias="contractVersion")
    renderer_version: str = Field(alias="rendererVersion", min_length=1)
    renderer_environment_version: str = Field(
        alias="rendererEnvironmentVersion", min_length=1
    )
    runtime_core_version: str = Field(alias="runtimeCoreVersion", min_length=1)
    runtime_core_source_hash: str = Field(alias="runtimeCoreSourceHash")
    runtime_core_bundle_hash: str = Field(alias="runtimeCoreBundleHash")
    state_machine_kernel_version: str = Field(alias="stateMachineKernelVersion", min_length=1)
    input_manifest_hash: str = Field(alias="inputManifestHash")
    document_object_hash: str = Field(alias="documentObjectHash")
    artifact_id: str = Field(alias="artifactId", min_length=1)
    files: list[_OutputFileDescriptor] = Field(min_length=1)
    bundle_hash: str = Field(alias="bundleHash")
    visual_preflight_report_hash: str = Field(alias="visualPreflightReportHash")


class _RenderResult(_StrictModel):
    input_manifest_hash: str = Field(alias="inputManifestHash")
    output_manifest: _OutputManifest = Field(alias="outputManifest")
    output_manifest_hash: str = Field(alias="outputManifestHash")
    visual_preflight_report: _PreflightReport = Field(alias="visualPreflightReport")
    visual_preflight_report_hash: str = Field(alias="visualPreflightReportHash")
    bundle_hash: str = Field(alias="bundleHash")
    files: list[_OutputFile] = Field(min_length=1)


class _RenderResponse(_SuccessResponse):
    action: Literal["render"]
    result: _RenderResult


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _require_hash(value: str, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise PrototypeRendererWorkerError(
            "renderer_worker_response_invalid",
            f"prototype renderer worker returned an invalid hash: {field}",
        )
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise PrototypeRendererWorkerError(
            "renderer_worker_response_invalid",
            f"prototype renderer worker returned an invalid hash: {field}",
        ) from exc


class PrototypeRendererWorker:
    def __init__(
        self,
        *,
        manifest_path: Path | None = None,
        node_executable: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("prototype renderer worker timeout must be positive")
        default_manifest = (
            Path(__file__).resolve().parent.parent
            / "runtime_assets"
            / "prototype_renderer_worker.manifest.json"
        )
        self.manifest_path = (manifest_path or default_manifest).resolve()
        self.timeout_s = timeout_s
        self._manifest = self._load_manifest()
        self.bundle_path = self._resolve_asset(self._manifest.bundle_file, "bundle")
        self.public_runtime_path = self._resolve_asset(
            self._manifest.public_runtime_file,
            "public runtime",
        )
        self.node_executable = node_executable or shutil.which("node") or ""
        if not self.node_executable:
            raise PrototypeRendererWorkerError(
                "renderer_worker_node_missing",
                "Node.js is required for the prototype renderer worker",
            )
        self.identity = PrototypeRendererWorkerIdentity(
            protocol_version=self._manifest.protocol_version,
            renderer_version=self._manifest.renderer_version,
            renderer_environment_version=self._manifest.renderer_environment_version,
            renderer_source_hash=self._manifest.renderer_source_hash,
            runtime_core_version=self._manifest.runtime_core_version,
            runtime_core_source_hash=self._manifest.runtime_core_source_hash,
            runtime_core_bundle_hash=self._manifest.runtime_core_bundle_hash,
            state_machine_kernel_version=self._manifest.state_machine_kernel_version,
            render_runtime_image_hash=self._manifest.render_runtime_image_hash,
            browser_version=self._manifest.browser_version,
            font_pack_hash=self._manifest.font_pack_hash,
            viewport_profile_hash=self._manifest.viewport_profile_hash,
            sandbox_policy_version=self._manifest.sandbox_policy_version,
            public_runtime_hash=self._manifest.public_runtime_hash,
            public_runtime_byte_size=self._manifest.public_runtime_byte_size,
            bundle_hash=self._manifest.bundle_hash,
            bundle_byte_size=self._manifest.bundle_byte_size,
            build_tool=self._manifest.build_tool,
            target=self._manifest.target,
        )
        self._verify_assets()

    async def describe(self, request_id: str) -> PrototypeRendererWorkerIdentity:
        response = await self._execute(
            action="describe",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "describe",
            },
            response_model=_DescribeResponse,
        )
        self._assert_identity_result(response.result)
        return self.identity

    async def render(
        self,
        *,
        request_id: str,
        artifact_id: str,
        input_manifest: dict[str, object],
        document: dict[str, object],
    ) -> PrototypeRendererWorkerResult:
        response = await self._execute(
            action="render",
            request={
                "protocolVersion": self.identity.protocol_version,
                "requestId": request_id,
                "action": "render",
                "artifactId": artifact_id,
                "inputManifest": input_manifest,
                "document": document,
            },
            response_model=_RenderResponse,
        )
        result = response.result
        for value, field in (
            (result.input_manifest_hash, "inputManifestHash"),
            (result.output_manifest_hash, "outputManifestHash"),
            (result.visual_preflight_report_hash, "visualPreflightReportHash"),
            (result.bundle_hash, "bundleHash"),
        ):
            _require_hash(value, field)
        expected_input_hash = _sha256(canonical_json_bytes(input_manifest))
        if result.input_manifest_hash != expected_input_hash:
            raise PrototypeRendererWorkerError(
                "renderer_worker_input_hash_mismatch",
                "prototype renderer worker input manifest hash does not match its request",
            )
        output_manifest = result.output_manifest.model_dump(mode="json", by_alias=True)
        preflight = result.visual_preflight_report.model_dump(mode="json", by_alias=True)
        if _sha256(canonical_json_bytes(output_manifest)) != result.output_manifest_hash:
            raise PrototypeRendererWorkerError(
                "renderer_worker_output_hash_mismatch",
                "prototype renderer worker output manifest hash is invalid",
            )
        if _sha256(canonical_json_bytes(preflight)) != result.visual_preflight_report_hash:
            raise PrototypeRendererWorkerError(
                "renderer_worker_preflight_hash_mismatch",
                "prototype renderer worker preflight report hash is invalid",
            )
        files = tuple(self._decode_file(file) for file in result.files)
        paths = tuple(file.relative_path for file in files)
        if paths != _ALLOWED_FILES:
            raise PrototypeRendererWorkerError(
                "renderer_worker_file_set_invalid",
                "prototype renderer worker returned an unsupported or unordered file set",
            )
        descriptors = [
            {
                "relativePath": file.relative_path,
                "byteSize": file.byte_size,
                "contentHash": file.content_hash,
            }
            for file in files
        ]
        if _sha256(canonical_json_bytes(descriptors)) != result.bundle_hash:
            raise PrototypeRendererWorkerError(
                "renderer_worker_bundle_hash_mismatch",
                "prototype renderer worker bundle hash is invalid",
            )
        if result.output_manifest.files != [
            _OutputFileDescriptor.model_validate(item, strict=True) for item in descriptors
        ]:
            raise PrototypeRendererWorkerError(
                "renderer_worker_output_manifest_mismatch",
                "prototype renderer worker output manifest files do not match its payload",
            )
        if (
            result.output_manifest.bundle_hash != result.bundle_hash
            or result.output_manifest.input_manifest_hash != result.input_manifest_hash
            or result.output_manifest.visual_preflight_report_hash
            != result.visual_preflight_report_hash
            or result.output_manifest.artifact_id != artifact_id
        ):
            raise PrototypeRendererWorkerError(
                "renderer_worker_output_manifest_mismatch",
                "prototype renderer worker output manifest identity is inconsistent",
            )
        return PrototypeRendererWorkerResult(
            input_manifest_hash=result.input_manifest_hash,
            output_manifest=output_manifest,
            output_manifest_hash=result.output_manifest_hash,
            visual_preflight_report=preflight,
            visual_preflight_report_hash=result.visual_preflight_report_hash,
            bundle_hash=result.bundle_hash,
            files=files,
        )

    def _load_manifest(self) -> _WorkerManifest:
        try:
            raw = self.manifest_path.read_bytes()
        except OSError as exc:
            raise PrototypeRendererWorkerError(
                "renderer_worker_manifest_missing",
                "prototype renderer worker manifest is unavailable",
            ) from exc
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise PrototypeRendererWorkerError(
                "renderer_worker_manifest_invalid",
                "prototype renderer worker manifest exceeds 256 KiB",
            )
        try:
            manifest = _WorkerManifest.model_validate_json(raw, strict=True)
        except ValidationError as exc:
            raise PrototypeRendererWorkerError(
                "renderer_worker_manifest_invalid",
                "prototype renderer worker manifest is invalid",
            ) from exc
        hash_fields = (
            (manifest.renderer_source_hash, "rendererSourceHash"),
            (manifest.runtime_core_source_hash, "runtimeCoreSourceHash"),
            (manifest.runtime_core_bundle_hash, "runtimeCoreBundleHash"),
            (manifest.render_runtime_image_hash, "renderRuntimeImageHash"),
            (manifest.font_pack_hash, "fontPackHash"),
            (manifest.viewport_profile_hash, "viewportProfileHash"),
            (manifest.public_runtime_hash, "publicRuntimeHash"),
            (manifest.bundle_hash, "bundleHash"),
        )
        for value, field in hash_fields:
            _require_hash(value, field)
        sources = [
            {"path": source.path, "hash": source.content_hash, "byteSize": source.byte_size}
            for source in manifest.sources
        ]
        for source in manifest.sources:
            _require_hash(source.content_hash, f"sources[{source.path}].hash")
        encoded = json.dumps(sources, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if _sha256(encoded) != manifest.renderer_source_hash:
            raise PrototypeRendererWorkerError(
                "renderer_worker_manifest_invalid",
                "prototype renderer worker source manifest hash does not match",
            )
        return manifest

    def _resolve_asset(self, relative_path: str, label: str) -> Path:
        directory = self.manifest_path.parent.resolve()
        unresolved = directory / relative_path
        if unresolved.is_symlink():
            raise PrototypeRendererWorkerError(
                "renderer_worker_asset_invalid",
                f"prototype renderer worker {label} must not be a symlink",
            )
        resolved = unresolved.resolve()
        try:
            resolved.relative_to(directory)
        except ValueError as exc:
            raise PrototypeRendererWorkerError(
                "renderer_worker_asset_invalid",
                f"prototype renderer worker {label} escapes its manifest directory",
            ) from exc
        return resolved

    def _verify_assets(self) -> None:
        for path, byte_size, content_hash, label in (
            (
                self.bundle_path,
                self.identity.bundle_byte_size,
                self.identity.bundle_hash,
                "bundle",
            ),
            (
                self.public_runtime_path,
                self.identity.public_runtime_byte_size,
                self.identity.public_runtime_hash,
                "public runtime",
            ),
        ):
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise PrototypeRendererWorkerError(
                    "renderer_worker_asset_missing",
                    f"prototype renderer worker {label} is unavailable",
                ) from exc
            if len(content) != byte_size or _sha256(content) != content_hash:
                raise PrototypeRendererWorkerError(
                    "renderer_worker_asset_hash_mismatch",
                    f"prototype renderer worker {label} does not match its manifest",
                )

    async def _execute(
        self,
        *,
        action: Literal["describe", "render"],
        request: dict[str, object],
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        self._verify_assets()
        request_id = request["requestId"]
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("prototype renderer worker request ID must not be empty")
        request_bytes = json.dumps(
            request,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        try:
            process = await asyncio.create_subprocess_exec(
                self.node_executable,
                "--max-old-space-size=192",
                str(self.bundle_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise PrototypeRendererWorkerError(
                "renderer_worker_spawn_failed",
                "prototype renderer worker process could not start",
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
            raise PrototypeRendererWorkerError(
                "renderer_worker_timeout",
                "prototype renderer worker exceeded its execution deadline",
            ) from exc
        if len(stdout) > _MAX_STDOUT_BYTES or len(stderr) > _MAX_STDERR_BYTES:
            raise PrototypeRendererWorkerError(
                "renderer_worker_output_too_large",
                "prototype renderer worker output exceeded its safety limit",
            )
        try:
            header = _ResponseIdentity.model_validate_json(stdout, strict=True)
        except ValidationError as exc:
            raise PrototypeRendererWorkerError(
                "renderer_worker_response_invalid",
                "prototype renderer worker returned an invalid response envelope",
            ) from exc
        self._assert_response_identity(header, request_id, action)
        if header.status == "error":
            try:
                failure = _WorkerErrorResponse.model_validate_json(stdout, strict=True)
            except ValidationError as exc:
                raise PrototypeRendererWorkerError(
                    "renderer_worker_response_invalid",
                    "prototype renderer worker returned invalid error evidence",
                ) from exc
            raise PrototypeRendererWorkerError(failure.error.code, failure.error.message)
        if process.returncode != 0:
            raise PrototypeRendererWorkerError(
                "renderer_worker_process_failed",
                "prototype renderer worker exited unsuccessfully",
            )
        try:
            return response_model.model_validate_json(stdout, strict=True)
        except ValidationError as exc:
            raise PrototypeRendererWorkerError(
                "renderer_worker_response_invalid",
                "prototype renderer worker returned an invalid success payload",
            ) from exc

    def _assert_response_identity(
        self,
        response: _ResponseIdentity,
        request_id: str,
        action: str,
    ) -> None:
        identity = self.identity
        if (
            response.request_id != request_id
            or response.action != action
            or response.protocol_version != identity.protocol_version
            or response.renderer_version != identity.renderer_version
            or response.renderer_environment_version != identity.renderer_environment_version
            or response.runtime_core_version != identity.runtime_core_version
            or response.runtime_core_source_hash != identity.runtime_core_source_hash
            or response.runtime_core_bundle_hash != identity.runtime_core_bundle_hash
            or response.state_machine_kernel_version != identity.state_machine_kernel_version
            or response.render_runtime_image_hash != identity.render_runtime_image_hash
            or response.browser_version != identity.browser_version
            or response.font_pack_hash != identity.font_pack_hash
            or response.viewport_profile_hash != identity.viewport_profile_hash
            or response.sandbox_policy_version != identity.sandbox_policy_version
        ):
            raise PrototypeRendererWorkerError(
                "renderer_worker_identity_mismatch",
                "prototype renderer worker response identity does not match its manifest",
            )

    def _assert_identity_result(self, result: _IdentityResult) -> None:
        identity = self.identity
        if (
            result.protocol_version != identity.protocol_version
            or result.renderer_version != identity.renderer_version
            or result.renderer_environment_version != identity.renderer_environment_version
            or result.runtime_core_version != identity.runtime_core_version
            or result.runtime_core_source_hash != identity.runtime_core_source_hash
            or result.runtime_core_bundle_hash != identity.runtime_core_bundle_hash
            or result.state_machine_kernel_version != identity.state_machine_kernel_version
            or result.render_runtime_image_hash != identity.render_runtime_image_hash
            or result.browser_version != identity.browser_version
            or result.font_pack_hash != identity.font_pack_hash
            or result.viewport_profile_hash != identity.viewport_profile_hash
            or result.sandbox_policy_version != identity.sandbox_policy_version
        ):
            raise PrototypeRendererWorkerError(
                "renderer_worker_identity_mismatch",
                "prototype renderer worker describe result does not match its manifest",
            )

    @staticmethod
    def _decode_file(file: _OutputFile) -> PrototypeRenderedFile:
        _require_hash(file.content_hash, f"files[{file.relative_path}].contentHash")
        try:
            content = base64.b64decode(file.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PrototypeRendererWorkerError(
                "renderer_worker_file_invalid",
                "prototype renderer worker returned invalid base64 file content",
            ) from exc
        if len(content) != file.byte_size or _sha256(content) != file.content_hash:
            raise PrototypeRendererWorkerError(
                "renderer_worker_file_hash_mismatch",
                f"prototype renderer worker file {file.relative_path} does not match its descriptor",
            )
        return PrototypeRenderedFile(
            relative_path=file.relative_path,
            content=content,
            byte_size=file.byte_size,
            content_hash=file.content_hash,
        )
