"""Šifrovaný trezor pre vratnú pseudonymizáciu.

Formát: JSON obálka s parametrami scrypt + AES-256-GCM. Obsah (po dešifrovaní):
  tokens     {"[OSOBA_001]": "Ján Novák", ...}   - mapovanie pre spätné nahradenie
  clusters   identita entít (aby rovnaká osoba dostala rovnaký token naprieč dokumentmi)
  counters   posledné pridelené číslo pre každý typ
  originals  {sha256 anonymizovaného súboru: pôvodný súbor v base64} - pre PDF
Trezor vždy uchovávajte oddelene od anonymizovaných dokumentov.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = "anonymizer-sk-vault"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1


class VaultError(Exception):
    pass


def _key(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


class Vault:
    def __init__(self, data: dict | None = None):
        self.data = data or {"tokens": {}, "clusters": {}, "counters": {}, "originals": {}}

    # ------------------------------------------------------------------ I/O
    @classmethod
    def open(cls, path: str | Path, passphrase: str) -> "Vault":
        env = json.loads(Path(path).read_text(encoding="utf-8"))
        if env.get("magic") != MAGIC:
            raise VaultError("Súbor nie je trezor anonymizer-sk.")
        kdf = env["kdf"]
        key = _key(passphrase, base64.b64decode(kdf["salt"]), kdf["n"], kdf["r"], kdf["p"])
        try:
            plain = AESGCM(key).decrypt(base64.b64decode(env["nonce"]), base64.b64decode(env["ciphertext"]),
                                        MAGIC.encode())
        except Exception as exc:
            raise VaultError("Nesprávne heslo alebo poškodený trezor.") from exc
        return cls(json.loads(plain))

    def save(self, path: str | Path, passphrase: str) -> None:
        salt, nonce = os.urandom(16), os.urandom(12)
        key = _key(passphrase, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        plain = json.dumps(self.data, ensure_ascii=False).encode("utf-8")
        env = {
            "magic": MAGIC, "version": 1, "cipher": "AES-256-GCM",
            "kdf": {"name": "scrypt", "salt": base64.b64encode(salt).decode(), "n": SCRYPT_N, "r": SCRYPT_R,
                    "p": SCRYPT_P},
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(AESGCM(key).encrypt(nonce, plain, MAGIC.encode())).decode(),
        }
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps(env), encoding="utf-8")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------ originály (PDF)
    def store_original(self, anonymized: bytes, original: bytes) -> None:
        self.data["originals"][hashlib.sha256(anonymized).hexdigest()] = base64.b64encode(original).decode()

    def get_original(self, anonymized: bytes) -> bytes | None:
        b = self.data["originals"].get(hashlib.sha256(anonymized).hexdigest())
        return base64.b64decode(b) if b else None
