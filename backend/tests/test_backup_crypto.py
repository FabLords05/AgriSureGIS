import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import backup_crypto
from app.core.backup_crypto import BackupCryptoError, decrypt_file, encrypt_file, load_key

KEY = os.urandom(32)


class BackupCryptoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _round_trip(self, data: bytes) -> bytes:
        plain, sealed, out = self.dir / "a.dump", self.dir / "a.enc", self.dir / "b.dump"
        plain.write_bytes(data)
        encrypt_file(plain, sealed, KEY)
        decrypt_file(sealed, out, KEY)
        return out.read_bytes()

    def test_round_trip_small_and_empty(self):
        self.assertEqual(self._round_trip(b"pg dump bytes"), b"pg dump bytes")
        self.assertEqual(self._round_trip(b""), b"")

    def test_round_trip_across_chunks(self):
        with patch.object(backup_crypto, "CHUNK_SIZE", 10):
            data = os.urandom(95)
            self.assertEqual(self._round_trip(data), data)

    def test_wrong_key_fails(self):
        plain, sealed = self.dir / "a.dump", self.dir / "a.enc"
        plain.write_bytes(b"secret")
        encrypt_file(plain, sealed, KEY)
        with self.assertRaises(BackupCryptoError):
            decrypt_file(sealed, self.dir / "out", os.urandom(32))

    def test_truncated_file_fails(self):
        with patch.object(backup_crypto, "CHUNK_SIZE", 10):
            plain, sealed = self.dir / "a.dump", self.dir / "a.enc"
            plain.write_bytes(os.urandom(35))
            encrypt_file(plain, sealed, KEY)
            # Drop the last whole chunk: every remaining chunk still decrypts,
            # but the new last one was not sealed as "last".
            chunk_record = 12 + 4 + 10 + 16
            sealed.write_bytes(sealed.read_bytes()[: len(backup_crypto.MAGIC) + 3 * chunk_record])
            with self.assertRaises(BackupCryptoError):
                decrypt_file(sealed, self.dir / "out", KEY)

    def test_load_key_validates_length(self):
        self.assertIsNone(load_key(None))
        self.assertEqual(load_key(base64.b64encode(KEY).decode()), KEY)
        with self.assertRaises(BackupCryptoError):
            load_key(base64.b64encode(b"short").decode())


if __name__ == "__main__":
    unittest.main()
