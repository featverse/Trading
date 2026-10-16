"""Authentification de l'opérateur (un seul utilisateur : toi).

- mot de passe haché en scrypt (stdlib), jamais stocké en clair ;
- jetons signés HMAC-SHA256 : accès court (15 min) + rafraîchissement révocable (30 j) ;
- verrouillage après 5 échecs pendant 15 minutes ;
- les actions sensibles redemandent le mot de passe + une phrase de confirmation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Mot de passe trop court (12 caractères minimum).")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class TokenError(Exception):
    pass


def issue_token(secret: str, kind: str, ttl: int, now: float | None = None, jti: str | None = None) -> str:
    now = time.time() if now is None else now
    payload = {"sub": "operator", "kind": kind, "iat": int(now), "exp": int(now + ttl), "jti": jti or secrets.token_hex(12)}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(secret: str, token: str, kind: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    try:
        body, sig = token.split(".")
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise TokenError("Signature invalide.")
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError("Jeton illisible.") from exc
    if payload.get("kind") != kind:
        raise TokenError("Type de jeton incorrect.")
    if payload.get("exp", 0) < now:
        raise TokenError("Jeton expiré.")
    return payload


@dataclass
class LoginThrottle:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0

    def check(self, now: float) -> None:
        if now < self.locked_until:
            raise TokenError(f"Trop d'échecs : réessaie dans {int(self.locked_until - now)} s.")

    def fail(self, now: float) -> None:
        self.failures = [t for t in self.failures if now - t < LOCK_SECONDS] + [now]
        if len(self.failures) >= MAX_FAILURES:
            self.locked_until = now + LOCK_SECONDS
            self.failures.clear()

    def success(self) -> None:
        self.failures.clear()
