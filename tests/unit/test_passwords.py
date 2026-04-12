from __future__ import annotations

from infra.security import passwords


class _FakeBcrypt:
    def __init__(self, matches: tuple[bytes, bytes]) -> None:
        self.matches = matches

    def checkpw(self, raw_password: bytes, stored_password_hash: bytes) -> bool:
        return (raw_password, stored_password_hash) == self.matches


def test_hash_password_uses_sha256_hex_digest() -> None:
    assert passwords.hash_password("secret") == (
        "2bb80d537b1da3e38bd30361aa855686bde0eacd" "7162fef6a25fe97bf527a25b"
    )


def test_verify_password_accepts_sha256_hashes() -> None:
    stored_password_hash = passwords.hash_password("office123")

    assert passwords.verify_password("office123", stored_password_hash) is True


def test_verify_password_accepts_plaintext_legacy_values() -> None:
    assert passwords.verify_password("worker123", "worker123") is True


def test_verify_password_accepts_bcrypt_hashes(monkeypatch) -> None:
    fake_bcrypt = _FakeBcrypt((b"supervisor123", b"$2b$legacy-demo-hash"))
    monkeypatch.setattr(passwords, "_bcrypt", fake_bcrypt)

    assert passwords.verify_password("supervisor123", "$2b$legacy-demo-hash") is True


def test_verify_password_rejects_bcrypt_hashes_when_backend_missing(monkeypatch) -> None:
    monkeypatch.setattr(passwords, "_bcrypt", None)

    assert passwords.verify_password("supervisor123", "$2b$legacy-demo-hash") is False
