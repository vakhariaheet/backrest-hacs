# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-03-29

### Fixed
- Dashboard field names updated to match actual Backrest API responses (`id` instead of `planId`/`repoId`, `bytesAddedLast30days` instead of `bytesAdded`, `backupsSuccessLast30days` instead of `backupCount`, `backupsFailedLast30days` instead of `failedBackupCount`)
- Operation parsing now skips non-backup operations (`operationForget`, `operationIndexSnapshot`) when determining last backup stats — previously a forget or index op could overwrite the last backup's bytes/files data
- `STATUS_PENDING` and `STATUS_INPROGRESS` added to `last_backup_status` sensor options list, fixing "value not in options" errors when a backup is queued or running
- `Bytes Added (Last)` and `New Files (Last)` sensors now correctly show `0` instead of `Unknown` when a backup completes with no new data (proto3 omits zero-value fields from JSON)
- Pending backup operations no longer overwrite the last completed backup's status and stats

### Removed
- Repo-level sensors removed (Snapshot Count, Total Size, Uncompressed Size, Compression Ratio) — these values are not available from the Backrest dashboard API endpoint

## [0.1.0] - 2026-03-29

### Added
- Initial release of the Backrest HACS integration
- Config flow UI setup with host, port, SSL, username/password, and scan interval options
- Re-authentication and reconfigure flows
- Per-plan sensors: Last Backup Time, Last Backup Status, Last Backup Duration, Bytes Added (Last), New Files (Last), Bytes Added (30 Days), Backup Count (30 Days), Failure Count (30 Days), Next Scheduled Backup, Hours Since Last Backup
- Per-plan binary sensors: Backup Running, Backup Stale, Last Backup Failed
- Per-plan buttons: Trigger Backup, Apply Retention Policy
- Per-repo buttons: Run Prune, Run Integrity Check, Refresh Statistics, Unlock Repository
- Instance-level sensors: Repo Count, Plan Count, Active Operations
- Instance-level binary sensor: Connected
- HA event bus events: `backrest_backup_started`, `backrest_backup_completed`, `backrest_backup_failed`, `backrest_connection_lost`, `backrest_connection_restored`
- HA services: `trigger_backup`, `cancel_operation`, `run_repo_task`, `forget_snapshots`
- HACS-compatible release workflow with automatic zip packaging
