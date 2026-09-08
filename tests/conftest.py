import pytest


@pytest.fixture(autouse=True)
def strict_redesign_mode_by_default(monkeypatch):
    """Existing engineering tests remain strict; demo tests opt in explicitly."""
    monkeypatch.setenv("REDESIGN_MODE", "strict")
    monkeypatch.delenv("DEMO_STRONG_REDESIGN", raising=False)

