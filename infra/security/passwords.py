from __future__ import annotations

import hashlib
import hmac

try:
    import bcrypt as _bcrypt
except ModuleNotFoundError:
    _bcrypt = None


_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2x$", "$2y$")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(raw_password: str, stored_password_hash: str) -> bool:
    normalized_hash = stored_password_hash.strip()
    if not normalized_hash:
        return False

    if normalized_hash.startswith(_BCRYPT_PREFIXES):
        if _bcrypt is None:
            return False

        try:
            return _bcrypt.checkpw(
                raw_password.encode("utf-8"),
                normalized_hash.encode("utf-8"),
            )
        except ValueError:
            return False

    candidate_hash = hash_password(raw_password)
    return hmac.compare_digest(candidate_hash, normalized_hash) or hmac.compare_digest(
        raw_password,
        normalized_hash,
    )
