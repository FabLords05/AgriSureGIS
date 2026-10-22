"""
Encryption for backup files sent off-site (2026-10-22). Dumps hold farmer
PII, so the copy uploaded to Google Drive is encrypted with a key that only
lives in backend/.env (BACKUP_ENCRYPTION_KEY). The local dump in BACKUP_DIR
stays plain, on the same machine as the database it copies.

Format: AES-256-GCM over 4 MiB chunks, so a multi-GB dump never has to sit
in memory.

    MAGIC (8 bytes) | per chunk: nonce (12) | length (4, big-endian) | ciphertext+tag

Each chunk's associated data is its index plus a "last chunk" flag, so
chunks can't be reordered, dropped or the file cut short without decryption
failing.

Lose the key and every encrypted Drive copy is unreadable -- keep it
somewhere safe outside this machine too. Generate one with:
    python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
"""
import base64
import os
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"AGSBK001"
CHUNK_SIZE = 4 * 1024 * 1024
_NONCE_SIZE = 12


class BackupCryptoError(RuntimeError):
    pass


def load_key(raw: str | None) -> bytes | None:
    """BACKUP_ENCRYPTION_KEY (base64 of 32 bytes) -> key bytes; None if unset."""
    if not raw:
        return None
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except Exception as exc:
        raise BackupCryptoError("BACKUP_ENCRYPTION_KEY is not valid base64.") from exc
    if len(key) != 32:
        raise BackupCryptoError("BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256).")
    return key


def _aad(index: int, last: bool) -> bytes:
    return struct.pack(">Q?", index, last)


def encrypt_file(source: Path, target: Path, key: bytes) -> None:
    aes = AESGCM(key)
    size = source.stat().st_size
    with source.open("rb") as src, target.open("wb") as dst:
        dst.write(MAGIC)
        index, done = 0, 0
        while True:
            chunk = src.read(CHUNK_SIZE)
            done += len(chunk)
            last = done >= size
            nonce = os.urandom(_NONCE_SIZE)
            sealed = aes.encrypt(nonce, chunk, _aad(index, last))
            dst.write(nonce + struct.pack(">I", len(sealed)) + sealed)
            index += 1
            if last:
                break


def decrypt_file(source: Path, target: Path, key: bytes) -> None:
    aes = AESGCM(key)
    with source.open("rb") as src, target.open("wb") as dst:
        if src.read(len(MAGIC)) != MAGIC:
            raise BackupCryptoError("Not an AgriSureGIS encrypted backup (bad header).")
        index = 0
        header = src.read(_NONCE_SIZE + 4)
        while header:
            if len(header) < _NONCE_SIZE + 4:
                raise BackupCryptoError("Encrypted backup is truncated.")
            nonce, length = header[:_NONCE_SIZE], struct.unpack(">I", header[_NONCE_SIZE:])[0]
            sealed = src.read(length)
            if len(sealed) != length:
                raise BackupCryptoError("Encrypted backup is truncated.")
            header = src.read(_NONCE_SIZE + 4)
            try:
                dst.write(aes.decrypt(nonce, sealed, _aad(index, not header)))
            except Exception as exc:
                raise BackupCryptoError(
                    "Decryption failed: wrong BACKUP_ENCRYPTION_KEY, or the file was altered or cut short."
                ) from exc
            index += 1
        if index == 0:
            raise BackupCryptoError("Encrypted backup has no data.")
