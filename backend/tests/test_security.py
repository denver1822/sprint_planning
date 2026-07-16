import pytest

from app.core.errors import DomainError
from app.core.security import new_participant_token, new_public_code, token_hash
from app.services.jira import _safe_jira_base_url


def test_tokens_are_unique_and_hashed() -> None:
    first, second = new_participant_token(), new_participant_token()

    assert first != second
    assert token_hash(first) != first
    assert token_hash(first) == token_hash(first)
    assert len(new_public_code()) >= 20


@pytest.mark.parametrize("url", ["http://example.com", "https://127.0.0.1", "https://localhost", "https://[::1]"])
def test_jira_ssrf_guards_reject_unsafe_urls(url: str) -> None:
    with pytest.raises(DomainError):
        _safe_jira_base_url(url)
