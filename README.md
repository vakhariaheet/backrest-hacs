# Backrest for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/vakhariaheet/backrest-hacs.svg)](https://github.com/vakhariaheet/backrest-hacs/releases)
[![License](https://img.shields.io/github/license/vakhariaheet/backrest-hacs.svg)](LICENSE)

A Home Assistant integration for [Backrest](https://github.com/garethgeorge/backrest) — a web-accessible UI and orchestrator for [restic](https://restic.net/) backup software.

Monitor your backup jobs, track repository health, trigger backups manually, and receive HA events when backups start, finish, or fail — all from Home Assistant.

---

## Features

- **Sensors** — snapshot counts, repo sizes, backup duration, files added, next scheduled run, and more
- **Binary Sensors** — connection status, running state, failure detection, and stale backup alerts
- **Buttons** — trigger backups, prune/check/unlock repos, forget old snapshots
- **Services** — programmatic control from automations and scripts
- **Events** — real-time HA events for backup started, completed, failed, connection lost/restored

---

## Requirements

- Home Assistant 2024.1 or newer
- [Backrest](https://github.com/garethgeorge/backrest) running and accessible from your HA instance (default port: **9898**)

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations**
2. Click the three-dot menu → **Custom repositories**
3. Add `https://github.com/vakhariaheet/backrest-hacs` with category **Integration**
4. Search for **Backrest** and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/backrest` folder into your HA `custom_components/` directory
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Backrest**
3. Fill in the connection details:

| Field | Default | Description |
|---|---|---|
| Host | — | Backrest server IP or hostname |
| Port | `9898` | Backrest API port |
| Use SSL | Off | Enable HTTPS |
| Verify SSL | On | Verify SSL certificate (disable for self-signed certs) |
| Username | — | Leave blank if Backrest auth is disabled |
| Password | — | Leave blank if Backrest auth is disabled |

After setup, one device is created per Backrest instance. Additional devices are created for each repository and backup plan.

---

## Options

Adjust via **Settings → Devices & Services → Backrest → Configure**:

| Option | Default | Description |
|---|---|---|
| Scan interval | `60` s | How often to poll Backrest (10–3600 s) |
| Default stale threshold | `25` h | Hours after which a plan's "Backup Stale" sensor turns on |

---

## Entities

### Instance Sensors

| Entity | Description |
|---|---|
| Repository Count | Number of configured repositories |
| Plan Count | Number of configured backup plans |
| Active Operations | Number of currently running operations |

### Repository Sensors

One set per repository:

| Entity | Description |
|---|---|
| Snapshot Count | Total snapshots stored |
| Total Size | Total compressed size on disk |
| Uncompressed Size | Total size before compression |
| Compression Ratio | Compression efficiency (e.g. `2.5` = 2.5× smaller) |

### Plan Sensors

One set per backup plan:

| Entity | Description |
|---|---|
| Last Backup Time | Timestamp of the most recent backup attempt |
| Last Backup Status | `success`, `warning`, `error`, `user_cancelled`, `system_cancelled` |
| Backup Duration | How long the last backup took (seconds) |
| Bytes Added | Data added to the repo in the last backup |
| New Files | Number of new files in the last backup |
| Bytes Added (30d) | Total data added over the last 30 days |
| Backup Count (30d) | Number of backups in the last 30 days |
| Failure Count (30d) | Number of failed backups in the last 30 days |
| Next Backup | Next scheduled run (calculated from cron schedule) |
| Hours Since Backup | Time elapsed since last backup |

### Instance Binary Sensors

| Entity | Description |
|---|---|
| Connected | `on` when the last poll succeeded, `off` when the server is unreachable |

### Plan Binary Sensors

| Entity | Description |
|---|---|
| Is Running | `on` while a backup operation is active |
| Last Backup Failed | `on` if the most recent backup ended in error or warning |
| Backup Stale | `on` when no successful backup has run within the stale threshold |

> The stale threshold defaults to the value set in Options (default 25 h) but can be overridden per-plan using the `backrest.set_stale_threshold` service.

### Buttons

**Per plan:**

| Button | Action |
|---|---|
| Trigger Backup | Start a backup immediately |
| Forget Snapshots | Apply the plan's retention policy |

**Per repository:**

| Button | Action |
|---|---|
| Run Prune | Remove snapshots no longer needed by any retention policy |
| Run Check | Verify repository data integrity |
| Refresh Stats | Update repository statistics |
| Unlock Repository | Remove a stale lock file |

---

## Services

### `backrest.trigger_backup`

Trigger a backup for a plan.

```yaml
service: backrest.trigger_backup
data:
  config_entry_id: !input config_entry_id
  plan_id: "daily-home"
```

### `backrest.cancel_operation`

Cancel a running operation.

```yaml
service: backrest.cancel_operation
data:
  config_entry_id: !input config_entry_id
  operation_id: 42
```

### `backrest.run_repo_task`

Run a maintenance task on a repository.

```yaml
service: backrest.run_repo_task
data:
  config_entry_id: !input config_entry_id
  repo_id: "s3-main"
  task: "prune"   # prune | check | stats | unlock
```

### `backrest.forget_snapshots`

Apply retention policy for a plan.

```yaml
service: backrest.forget_snapshots
data:
  config_entry_id: !input config_entry_id
  plan_id: "daily-home"
```

### `backrest.list_snapshots`

List snapshots for a repository. Returns data as a service response.

```yaml
service: backrest.list_snapshots
data:
  config_entry_id: !input config_entry_id
  repo_id: "s3-main"
  plan_id: "daily-home"   # optional filter
  limit: 10
response_variable: snapshots
```

### `backrest.set_stale_threshold`

Override the stale threshold for a specific plan.

```yaml
service: backrest.set_stale_threshold
data:
  config_entry_id: !input config_entry_id
  plan_id: "weekly-archive"
  threshold_hours: 200   # ~8 days for a weekly backup
```

---

## Events

The integration fires events on the HA event bus that can be used in automations.

| Event | Fired when | Key payload fields |
|---|---|---|
| `backrest_backup_started` | A backup operation begins | `plan_id`, `operation_id` |
| `backrest_backup_completed` | A backup finishes (success or warning) | `plan_id`, `status`, `duration_seconds`, `bytes_added` |
| `backrest_backup_failed` | A backup ends in error | `plan_id`, `status` |
| `backrest_connection_lost` | The server becomes unreachable | `entry_id`, `host` |
| `backrest_connection_restored` | The server is reachable again | `entry_id`, `host` |

### Example automation — notify on backup failure

```yaml
automation:
  trigger:
    platform: event
    event_type: backrest_backup_failed
  action:
    service: notify.mobile_app_phone
    data:
      message: "Backup failed for plan {{ trigger.event.data.plan_id }}"
```

### Example automation — trigger backup at a specific time

```yaml
automation:
  trigger:
    platform: time
    at: "03:00:00"
  action:
    service: backrest.trigger_backup
    data:
      config_entry_id: "your_entry_id"
      plan_id: "daily-home"
```

---

## Re-authentication

If your Backrest credentials change, Home Assistant will show a re-authentication notification. Click it and enter the new username/password — no need to remove and re-add the integration.

---

## Running Tests

```bash
# First-time setup
uv venv .venv --python 3.12
uv pip install -r requirements_test.txt

# Run all tests
.venv/bin/pytest tests/

# Run a specific file
.venv/bin/pytest tests/test_coordinator.py

# With coverage
.venv/bin/pytest tests/ --cov=custom_components/backrest --cov-report=term-missing
```

---

## Contributing

Issues and pull requests are welcome at [github.com/vakhariaheet/backrest-hacs](https://github.com/vakhariaheet/backrest-hacs/issues).
