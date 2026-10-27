import pytest

import app as site


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    """Every test starts with an empty rate-limit history."""
    site.limiter.reset()
    yield
    site.limiter.reset()
