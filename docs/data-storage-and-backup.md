# Data storage, backup, and restore

`aetnamem` stores memory separately from files created in the assistant
workspace. Back up both if you want a complete copy of your local data. The
Ollama model is managed by Ollama and does not need to be included; it can be
downloaded again.

## Default desktop locations

| Platform | Memory database | Assistant workspace | At-rest protection |
|---|---|---|---|
| macOS launcher | `~/Library/Application Support/aetnamem/memories.db.enc` and `memories.db.enc.hmac` | `~/Aetnamem Workspace` | AES-256-CBC sealed copy with HMAC-SHA256 integrity; key in macOS Keychain |
| Linux launcher | `$XDG_DATA_HOME/aetnamem/memories.db` when set, otherwise `~/.local/share/aetnamem/memories.db` | `~/aetnamem-workspace` | Plaintext SQLite; rely on full-disk or home-directory encryption |
| Windows launcher | `%LOCALAPPDATA%\aetnamem\memories.db` | `%USERPROFILE%\Aetnamem Workspace` | Plaintext SQLite; rely on BitLocker or other disk encryption |

The macOS launcher decrypts the sealed database into a private temporary
directory while the app is open. The live SQLite file is plaintext during
that time and is removed after a clean shutdown. The path shown as "Live
memory database" in Settings is temporary and must not be used as the backup
location.

Running `aetnamem-service` directly, without a desktop launcher, defaults to
`~/.aetnamem/memories.db` and `~/.aetnamem/workspace` on every platform. The
actual locations can be changed with `--db`, `--workspace`, `AETNAMEM_DB`, and
`AETNAMEM_WORKSPACE`. On macOS, `--encrypted-db` or
`AETNAMEM_ENCRYPTED_DB` enables the sealed-database mode. The Settings page
and startup terminal output show the paths used by the current process.

## Back up macOS desktop data

1. Quit the aetnamem service normally with `Ctrl-C` in its Terminal window.
   Wait for the process to exit so the latest SQLite state is checkpointed and
   sealed.
2. Back up these two files together:

   ```text
   ~/Library/Application Support/aetnamem/memories.db.enc
   ~/Library/Application Support/aetnamem/memories.db.enc.hmac
   ```

3. Back up `~/Aetnamem Workspace` if you also need assistant-created files.
4. Keep a recoverable copy of the `aetnamem` login-Keychain item. A file
   backup without the key cannot be opened on a replacement Mac. To display
   the recovery value for transfer into a trusted password manager:

   ```bash
   security find-generic-password -s aetnamem -a database-key -w
   ```

   This prints a secret. Do not put it in a screenshot, unencrypted note,
   shell script, cloud log, or repository.

To restore on another Mac, quit aetnamem, place both sealed files at the same
paths, restore the workspace if required, and restore the Keychain value:

```bash
read -s "AETNAMEM_DATABASE_KEY?Database recovery key: "; echo
security add-generic-password -U -s aetnamem -a database-key \
  -w "$AETNAMEM_DATABASE_KEY"
unset AETNAMEM_DATABASE_KEY
```

Then launch aetnamem normally. A missing or wrong key, missing `.hmac` file,
or modified encrypted file causes startup to fail instead of silently opening
unverified data.

## Back up Linux or Windows desktop data

Stop aetnamem before copying the database. SQLite may use `-wal` and `-shm`
files while running, so copying only `memories.db` from a live process can
produce an incomplete backup.

On Linux, copy the database and workspace to your backup destination:

```bash
cp "${XDG_DATA_HOME:-$HOME/.local/share}/aetnamem/memories.db" /path/to/backup/
cp -R "$HOME/aetnamem-workspace" /path/to/backup/
```

On Windows, after closing the service, copy these locations using File
Explorer, Windows Backup, or your normal backup software:

```text
%LOCALAPPDATA%\aetnamem\memories.db
%USERPROFILE%\Aetnamem Workspace
```

Restore the database and workspace to the same locations before restarting
the app. Preserve the file as binary data; do not open or rewrite it with a
text editor. Linux and Windows desktop databases are not encrypted by
`aetnamem`, so the backup destination should itself be encrypted.

## Encryption boundary on macOS

The macOS sealed mode uses OpenSSL AES-256-CBC with PBKDF2 and a random salt.
It authenticates the encrypted bytes with HMAC-SHA256 before decryption, and
the random 256-bit recovery value is stored in the macOS login Keychain. This
provides useful protection against someone obtaining the idle database files
without the Keychain key.

It is not full live-database encryption such as SQLCipher. In particular:

- the database is plaintext in a user-private temporary directory while the
  service is running;
- an unclean crash can leave temporary plaintext until macOS cleans the
  temporary directory and can lose changes made after the last successful
  seal;
- the encrypted file and its HMAC sidecar are replaced separately, so a crash
  during sealing can require recovery from backup;
- the same high-entropy recovery secret supplies both the OpenSSL password and
  the HMAC key; a future hardened format should derive separate, domain-specific
  keys;
- malware or another process running as the signed-in user may access the live
  database or ask Keychain for the key, subject to Keychain access controls;
- backup confidentiality and key recovery remain the user's responsibility.

Use FileVault on macOS and BitLocker or equivalent disk encryption on Windows
in addition to aetnamem's application-level controls.
