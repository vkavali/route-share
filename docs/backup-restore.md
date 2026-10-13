# Private database backup and restore drill

`scripts/backup_store.py` creates consistent, self-contained snapshots with SQLite's online backup API, including private document BLOBs and identity/session records. It does not activate hosted backups, deploy, switch the running database or schedule work. The isolated tests establish local recovery behavior only; a production backup and restore drill remain operator tasks.

Run on the database host with authorized filesystem access. Choose an owner-only directory on a filesystem that enforces private permissions; the command refuses permissive filesystems. The backup directory must not exist. Example paths below are placeholders, not known production backups:

```sh
python3 scripts/backup_store.py backup \
  --database /private/app/beta.sqlite3 \
  --output /private/backups/beta-20261008
python3 scripts/backup_store.py restore \
  --backup /private/backups/beta-20261008 \
  --destination /private/restore-drill/beta.sqlite3
```

Create the private parent directories first. Restore refuses an existing destination, symlink or SQLite sidecar. It validates the snapshot hash, SQLite integrity, required document-store schema, document/BLOB counts and phone-key fingerprint continuity. New format-2 manifests also inventory identity evidence tables, fingerprint their encrypted rows and record a digest of the encrypted identity-key binding token; restore compares these values before and after copying. Older databases without either document BLOB table remain supported. Existing format-1 manifests remain restorable with their original inventory checks, and the restore drill compares their copied database against a fresh full inventory of the snapshot. The manifest contains counts and hashes, not record contents, phones, document identifiers, uploaded evidence or secret keys. Hashes detect accidental modification, not malicious replacement of both snapshot and manifest.

The database snapshot itself **contains sensitive records**, including private uploaded documents and session metadata. Do not add it to source archives, Git, public storage, support attachments or general logs. File permissions are not encryption; use approved encrypted storage and restrict access and retention separately. A local copy on the same disk is not disaster recovery.

Preserve the external `PHONE_AUTH_HMAC_KEY` and `IDENTITY_EVIDENCE_KEY` separately through the operator's private secret-management process, retaining the existing values unchanged. Neither key is exported by this command. The restored phone fingerprint proves the database retained its prior phone identity-key binding. The identity configuration digest proves the encrypted key-binding token was copied unchanged; it does not contain or recover the external key. Starting identity review without the matching `IDENTITY_EVIDENCE_KEY` leaves encrypted evidence unavailable, and changing the key is not a migration. Also retain the appropriate external service configuration through the approved secret process. Do not paste keys into commands, manifests or review evidence. Never generate a replacement key as part of a restore drill.

Before a real recovery, validate the restored database in isolation with the intended application version and unchanged phone key, network/SMS/UPI disabled, and authorized synthetic probes. Check expected records and BLOB retrieval privately. Restoring an older snapshot can restore old sessions, approvals, consent and records previously deleted: reconcile security revocations and retention/deletion history before allowing customers back. Never run the restored copy as a second public writer. Stop the original writer and obtain an explicit reviewed cutover before changing the live database path; these commands deliberately provide no automatic cutover or destructive rollback.

Source runtime rollback is separate from database recovery. A hosted volume and successful deployment are not evidence of an off-host backup, tested restore, protected backup retention or deletion from WAL/backup history. No backup automation or hosted configuration is introduced here.
