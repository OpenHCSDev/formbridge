"""Nominal registration gates for host-provided UI behavior."""

import pytest

from formbridge.protocols.component_selection import (
    ComponentSelectionProviderABC,
    FunctionSelectionProviderABC,
    register_component_selection_provider,
    register_function_selection_provider,
)
from formbridge.protocols.log_providers import (
    LogDiscoveryProviderABC,
    ServerScanProviderABC,
    register_log_discovery_provider,
    register_server_scan_provider,
)


@pytest.mark.parametrize(
    ("contract", "register", "message"),
    (
        (
            LogDiscoveryProviderABC,
            register_log_discovery_provider,
            "inherit LogDiscoveryProviderABC",
        ),
        (
            ServerScanProviderABC,
            register_server_scan_provider,
            "inherit ServerScanProviderABC",
        ),
        (
            ComponentSelectionProviderABC,
            register_component_selection_provider,
            "inherit ComponentSelectionProviderABC",
        ),
        (
            FunctionSelectionProviderABC,
            register_function_selection_provider,
            "inherit FunctionSelectionProviderABC",
        ),
    ),
)
def test_host_provider_registration_requires_nominal_contract(
    contract,
    register,
    message: str,
) -> None:
    class StructuralProvider:
        pass

    with pytest.raises(TypeError):
        contract()

    with pytest.raises(TypeError, match=message):
        register(StructuralProvider())
