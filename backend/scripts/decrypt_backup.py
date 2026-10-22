"""
Decrypts a Google Drive backup copy (*.dump.enc) back into a pg_restore-able
.dump, using BACKUP_ENCRYPTION_KEY from backend/.env (see
app/core/backup_crypto.py). Part of the manual live-restore runbook in
.claude/ENV_GUIDE.md -- the app itself never restores over the live database.

Run from backend/:
    python scripts/decrypt_backup.py path/to/agrisure_manual_2026-10-22_230000.dump.enc
    python scripts/decrypt_backup.py in.dump.enc out.dump
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from app.core.backup_crypto import BackupCryptoError, decrypt_file, load_key


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    source = Path(sys.argv[1])
    target = Path(sys.argv[2]) if len(sys.argv) == 3 else source.with_suffix("")
    if target.suffix != ".dump":
        target = target.with_suffix(".dump")
    if target.exists():
        sys.exit(f"{target} already exists -- not overwriting it.")

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    try:
        key = load_key(os.getenv("BACKUP_ENCRYPTION_KEY"))
        if key is None:
            sys.exit("BACKUP_ENCRYPTION_KEY is not set in backend/.env.")
        decrypt_file(source, target, key)
    except BackupCryptoError as exc:
        target.unlink(missing_ok=True)
        sys.exit(str(exc))
    print(f"Decrypted to {target}")


if __name__ == "__main__":
    main()
