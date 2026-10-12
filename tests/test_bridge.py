"""The running-UI bridge serves any application that declares itself once."""

from __future__ import annotations

from pathlib import Path

import pytest
from zmqruntime.config import TransportMode

from formbridge.bridge.application import UiBridgeApplication
from formbridge.bridge.dto import UiWindowSnapshotRequest
from formbridge.bridge.identities import UiStableWindowIdentityDeclaration
from formbridge.bridge.in_process import UiAgentBridgeService
from formbridge.bridge.scope_policy import HiddenObjectStateScope, ObjectStateScopeVisibility
from formbridge.bridge.server import UiBridgeControlServer, UiBridgeServerConfig
from formbridge.bridge.service import (
    UiBridgeListDocumentsOperation,
    UiBridgeOperation,
    UiBridgeService,
    UiBridgeStatusOperation,
)
from formbridge.services.main_thread_dispatch import MainThreadDispatcher


class InlineDispatcher(MainThreadDispatcher):
    """Every caller owns the work: the test thread stands in for the UI thread."""

    def _is_owner_thread(self) -> bool:
        return True

    def _can_deliver(self) -> bool:
        return True

    def _deliver(self, call) -> None:
        call.run()


class ExampleSettingsWindow(UiStableWindowIdentityDeclaration):
    value = "example_settings"
    title = "Settings"
    manager_scope_alias = ""


class ExampleSystemScope(HiddenObjectStateScope):
    scope_id = "__example_rows__"


def test_the_one_declared_application_is_current() -> None:
    from conftest import ExampleBridgeApplication

    assert UiBridgeApplication.current() is ExampleBridgeApplication


def test_every_wire_operation_answers_its_own_failure() -> None:
    base_failed = UiBridgeOperation.failed.__func__
    base_respond = UiBridgeOperation.respond.__func__
    silent = [
        operation.__name__
        for operation in UiBridgeOperation.__registry__.values()
        if operation.failed.__func__ is base_failed and operation.respond.__func__ is base_respond
    ]
    assert silent == []


def test_generic_bridge_serves_every_generic_operation() -> None:
    assert set(UiAgentBridgeService.served_operations) == set(
        UiBridgeOperation.__registry__.values()
    )


def test_window_identity_declares_its_manager_scope_alias() -> None:
    declared = UiStableWindowIdentityDeclaration
    assert declared.window_id_for_manager_scope("") == "example_settings"
    assert declared.window_id_for_manager_scope("other") == "other"
    assert declared.manager_scopes_for_window_id("example_settings") == ("example_settings", "")
    assert declared.manager_scope_for_window_id("example_settings") == ""


def test_declared_system_scope_is_hidden_until_asked_for() -> None:
    visibility = ObjectStateScopeVisibility()
    assert not visibility.includes_scope_id("__example_rows__")
    assert visibility.includes_scope_id("plate-a")


def test_snapshot_request_defaults_to_the_application_directory() -> None:
    request = UiWindowSnapshotRequest.from_fields(window_id="example_settings")
    assert Path(request.output_dir_path) == Path("/tmp/example-snapshots")


@pytest.mark.parametrize("transport_mode", (TransportMode.TCP,))
def test_client_reaches_server_through_its_descriptor(tmp_path, transport_mode) -> None:
    bridge = UiAgentBridgeService(dispatcher=InlineDispatcher())
    server = UiBridgeControlServer(
        bridge,
        UiBridgeServerConfig(
            port=None,
            transport_mode=transport_mode,
            descriptor_directory_path=tmp_path,
            bridge_instance_id="example-bridge",
            auth_token="example-token",
        ),
    )
    binding = server.start()
    try:
        service = UiBridgeService()
        connection = service.connection_from_args(descriptor_file_path=binding.descriptor_file_path)
        status = service.invoke(UiBridgeStatusOperation, connection=connection)
        documents = service.invoke(UiBridgeListDocumentsOperation, connection=connection)
    finally:
        server.stop()
        bridge.close()

    assert status.reachable is True, status.errors
    assert status.service == "example.ui_bridge"
    assert status.bridge_instance_id == "example-bridge"
    assert set(status.supported_operations) == set(UiBridgeOperation.__registry__)
    assert documents.documents == ()
    assert documents.errors == ()
