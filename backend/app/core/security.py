import hashlib
import hmac
import secrets

from app.core.config import get_settings


def new_participant_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    secret = get_settings().secret_key.encode("utf-8")
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def new_public_code() -> str:
    # 16 random bytes provide 128 bits of entropy, above the contract minimum of 96 bits.
    return secrets.token_urlsafe(16)

