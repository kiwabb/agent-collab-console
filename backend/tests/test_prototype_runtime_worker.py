from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from app.adapters import prototype_runtime_worker as runtime_worker_module
from app.adapters.prototype_runtime_worker import (
    PrototypeRuntimeWorker,
    PrototypeRuntimeWorkerError,
)
from app.json_safety import object_dict_or_none


def _runtime_definition() -> dict[str, object]:
    return {
        "runtimeSchemaVersion": 1,
        "pageIds": ["page-list"],
        "roles": [
            {"id": "role-applicant", "key": "applicant", "label": "申请人"},
            {"id": "role-manager", "key": "manager", "label": "主管"},
        ],
        "variables": [],
        "entitySchemas": [],
        "forms": [],
        "viewBindings": [],
        "rules": [],
        "scenarios": [
            {
                "id": "scenario-happy-path",
                "key": "happy-path",
                "actorRoleId": "role-applicant",
                "startPageId": "page-list",
                "initialVariables": [],
                "entityFixtures": [],
                "allowSimulatedRoleSwitch": True,
            }
        ],
    }


def _role_switch_batch() -> dict[str, object]:
    return {
        "clientEventId": "switch-to-manager",
        "expectedSequenceNo": 0,
        "events": [{"kind": "switchSimulatedRole", "roleId": "role-manager"}],
    }


def _runtime_asset_paths() -> tuple[Path, Path]:
    directory = Path(__file__).resolve().parent.parent / "app" / "runtime_assets"
    return (
        directory / "prototype_runtime_worker.manifest.json",
        directory / "prototype_runtime_worker.mjs",
    )


class _HungProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False

    async def communicate(self, request_bytes: bytes) -> tuple[bytes, bytes]:
        await asyncio.Future()
        return b"", b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


@pytest.mark.asyncio
async def test_node_worker_initializes_applies_and_replays_with_verified_identity() -> None:
    worker = PrototypeRuntimeWorker()
    definition = _runtime_definition()
    identity = await worker.describe("describe-integration")
    initial = await worker.initialize_state(
        request_id="initialize-integration",
        definition=definition,
        scenario_id="scenario-happy-path",
        session_id="runtime-worker-integration",
    )
    transitioned = await worker.apply_event_batch(
        request_id="apply-integration",
        definition=definition,
        state_json=initial.state_json,
        batch=_role_switch_batch(),
    )
    replayed = await worker.replay_event_batches(
        request_id="replay-integration",
        definition=definition,
        state_json=initial.state_json,
        batches=[_role_switch_batch()],
    )
    state: object = json.loads(transitioned.state_json)
    state_record = object_dict_or_none(state)

    assert identity.runtime_core_version == "0.2.0-spike"
    assert identity.state_machine_kernel_version == "5.32.4"
    assert identity.runtime_core_source_hash.startswith("sha256:")
    assert identity.runtime_core_bundle_hash.startswith("sha256:")
    assert state_record is not None
    assert state_record["actorRoleId"] == "role-manager"
    assert state_record["sequenceNo"] == 1
    assert transitioned.base_sequence_no == 0
    assert transitioned.result_sequence_no == 1
    assert transitioned.outcome == "applied"
    assert replayed.transitions == (transitioned,)
    assert replayed.final.state_hash == transitioned.state_hash
    assert replayed.final.view_model_hash == transitioned.view_model_hash


@pytest.mark.asyncio
async def test_worker_uses_configured_deadline_and_kills_timed_out_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _HungProcess()
    observed_timeout: float | None = None

    async def create_process(*args: object, **kwargs: object) -> _HungProcess:
        return process

    async def time_out(awaitable: object, *, timeout: float) -> tuple[bytes, bytes]:
        nonlocal observed_timeout
        observed_timeout = timeout
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        raise TimeoutError

    monkeypatch.setattr(runtime_worker_module.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(runtime_worker_module.asyncio, "wait_for", time_out)
    worker = PrototypeRuntimeWorker(timeout_s=30.0)

    with pytest.raises(PrototypeRuntimeWorkerError) as error:
        await worker.describe("describe-timeout")

    assert error.value.code == "runtime_worker_timeout"
    assert observed_timeout == 30.0
    assert process.killed is True


@pytest.mark.asyncio
async def test_worker_refuses_a_bundle_changed_after_manifest_verification(tmp_path: Path) -> None:
    source_manifest, source_bundle = _runtime_asset_paths()
    manifest = tmp_path / source_manifest.name
    bundle = tmp_path / source_bundle.name
    shutil.copyfile(source_manifest, manifest)
    shutil.copyfile(source_bundle, bundle)
    worker = PrototypeRuntimeWorker(manifest_path=manifest)
    bundle.write_bytes(bundle.read_bytes() + b"\n// changed after verification\n")

    with pytest.raises(PrototypeRuntimeWorkerError) as error:
        await worker.describe("describe-corrupt-bundle")

    assert error.value.code == "runtime_worker_bundle_hash_mismatch"


def test_worker_refuses_a_tampered_source_manifest_hash(tmp_path: Path) -> None:
    source_manifest, source_bundle = _runtime_asset_paths()
    manifest = tmp_path / source_manifest.name
    bundle = tmp_path / source_bundle.name
    shutil.copyfile(source_bundle, bundle)
    raw: object = json.loads(source_manifest.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["runtimeCoreSourceHash"] = "sha256:" + "0" * 64
    manifest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(PrototypeRuntimeWorkerError) as error:
        PrototypeRuntimeWorker(manifest_path=manifest)

    assert error.value.code == "runtime_worker_manifest_invalid"


@pytest.mark.asyncio
async def test_worker_surfaces_strict_input_errors_without_fallback() -> None:
    worker = PrototypeRuntimeWorker()
    invalid_definition = _runtime_definition()
    invalid_definition["unexpected"] = True

    with pytest.raises(PrototypeRuntimeWorkerError) as error:
        await worker.initialize_state(
            request_id="initialize-invalid",
            definition=invalid_definition,
            scenario_id="scenario-happy-path",
            session_id="runtime-worker-invalid",
        )

    assert error.value.code == "runtime_input_invalid"
