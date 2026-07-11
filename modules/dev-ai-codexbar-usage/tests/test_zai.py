from __future__ import annotations

from datetime import datetime, timezone

import pytest

from codexbar_usage.providers import PROVIDER_MODULE_MAP
from codexbar_usage.providers.zai import ZaiProvider


def test_zai_provider_is_registered() -> None:
    assert PROVIDER_MODULE_MAP["zai"] == "zai"


def test_zai_provider_parses_token_and_time_windows() -> None:
    snapshot = ZaiProvider(api_key="test").parse_usage(
        {
            "data": {
                "planName": "Pro",
                "limits": [
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 3,
                        "number": 5,
                        "percentage": 25,
                        "nextResetTime": 1_800_000_000_000,
                    },
                    {
                        "type": "TIME_LIMIT",
                        "unit": 3,
                        "number": 1,
                        "percentage": 50,
                    },
                ],
            }
        }
    )

    assert snapshot.primary is not None
    assert snapshot.primary.used_percent == 0.25
    assert snapshot.primary.window_minutes == 300
    assert snapshot.primary.resets_at == datetime.fromtimestamp(1_800_000_000, timezone.utc)
    assert snapshot.secondary is not None
    assert snapshot.secondary.used_percent == 0.5
    assert snapshot.secondary.window_minutes == 60
    assert snapshot.identity is not None
    assert snapshot.identity.account_organization == "Pro"


@pytest.mark.parametrize(("percentage", "expected"), [(0, 0.0), (1, 0.01), (100, 1.0)])
def test_zai_percentage_is_always_zero_to_one(percentage: int, expected: float) -> None:
    snapshot = ZaiProvider(api_key="test").parse_usage(
        {"data": {"limits": [{"type": "TOKENS_LIMIT", "percentage": percentage}]}}
    )
    assert snapshot.primary is not None
    assert snapshot.primary.used_percent == expected


def test_zai_malformed_percentage_fails_closed() -> None:
    with pytest.raises(ValueError):
        ZaiProvider(api_key="test").parse_usage(
            {"data": {"limits": [{"type": "TOKENS_LIMIT", "percentage": "bad"}]}}
        )
