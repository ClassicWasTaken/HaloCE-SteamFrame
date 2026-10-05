# Reporting security problems

Do not include passwords, private keys, game data, or personal setup logs in a public issue. Report security problems through the repository's private vulnerability reporting feature if enabled, or contact the maintainer privately through an available profile contact.

The installer uses encrypted SSH and explicit SHA256 host-key approval. A changed saved host key is refused. Only public host fingerprints are persisted. Passwords are never stored in project files or passed in command-line arguments.

The Xbox image parser treats selected files as untrusted, bounds directory/file ranges, rejects unsafe paths and symlinks, and only extracts known retail maps. Remote writes are limited to owned per-user directories. The installer never disables SteamOS read-only mode or uses sudo to install packages.

The source revision is fixed, but the native build still downloads an Ubuntu container and toolchain/dependencies from their upstream distributors. This is not an offline or completely hermetic build. Updates to the fixed source and controller patch must be reviewed and tested together.

Cancellation stops the installer-owned build container; an already completed installation may remain. Repairs back up program files and roll back a failed transaction, preserving saves and unrelated settings. Supplied valid Xbox maps may replace existing maps with backups; no-image repairs reuse existing verified maps. Unknown native folders are adopted only through an explicit Repair request and strict native/data validation. Library registration edits Steam shortcuts only while the Steam client is closed, with a backup and unrelated entries preserved.
