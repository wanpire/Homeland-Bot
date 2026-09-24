"""The one platform/protocol compatibility rule the handover sequence uses."""

from __future__ import annotations

import pytest

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.services.tutorials import protocols_for_platform

_PROTOCOLS = [TutorialProtocol(id=1, label="OpenVPN"), TutorialProtocol(id=2, label="L2TP")]


def test_android_is_left_with_openvpn_only() -> None:
    assert [p.label for p in protocols_for_platform(TutorialPlatform(label="Android"), _PROTOCOLS)] == ["OpenVPN"]


def test_the_rule_ignores_case_and_padding() -> None:
    protocols = [TutorialProtocol(label="openvpn"), TutorialProtocol(label=" l2tp ")]
    assert [p.label for p in protocols_for_platform(TutorialPlatform(label=" android "), protocols)] == ["openvpn"]


@pytest.mark.parametrize("label", ["iOS", "Windows", "macOS"])
def test_other_devices_keep_every_protocol_in_order(label: str) -> None:
    assert protocols_for_platform(TutorialPlatform(label=label), _PROTOCOLS) == _PROTOCOLS
