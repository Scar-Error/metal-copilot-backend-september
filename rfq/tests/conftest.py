"""Test-wide guard: no test may reach a real AI provider.

The categorize endpoint classifies and extracts through whatever provider
`get_ai_provider()` builds. With no key configured every call failed instantly,
which hid the problem: as soon as a real key was in `.env` a test run made
dozens of live Claude calls — real money, real latency, and results that
changed with the model's mood.

A test that needs AI injects a fake provider or patches the method it is
testing; everything else gets "no provider", which is the honest answer for a
test. The fixture is function-scoped and undone automatically.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_live_ai(monkeypatch):
    from rfq import ai_classifier, data_extractors
    from rfq.ai_providers import AIProviderUnavailable

    def unavailable(*_args, **_kwargs):
        raise AIProviderUnavailable('AI provider disabled in tests')

    monkeypatch.setattr(ai_classifier, 'get_ai_provider', unavailable)
    monkeypatch.setattr(data_extractors, 'get_ai_provider', unavailable)
