"""Constants for the Backrest integration."""
from __future__ import annotations

DOMAIN = "backrest"
INTEGRATION_NAME = "Backrest Backup Manager"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_USE_SSL = "use_ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STALE_THRESHOLDS = "stale_thresholds"  # dict {plan_id: hours}

# Defaults
DEFAULT_PORT = 9898
DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_STALE_THRESHOLD_HOURS = 25  # 24h + 1h slack for daily backups
DEFAULT_TIMEOUT = 30  # seconds per request

# Platforms
PLATFORMS = ["sensor", "binary_sensor", "button"]

# API paths
AUTH_SERVICE_PATH = "v1.Authentication"
BACKREST_SERVICE_PATH = "v1.Backrest"

# API methods
METHOD_LOGIN = "Login"
METHOD_GET_CONFIG = "GetConfig"
METHOD_SET_CONFIG = "SetConfig"
METHOD_ADD_REPO = "AddRepo"
METHOD_REMOVE_REPO = "RemoveRepo"
METHOD_CHECK_REPO_EXISTS = "CheckRepoExists"
METHOD_GET_OPERATIONS = "GetOperations"
METHOD_GET_OPERATION_EVENTS = "GetOperationEvents"
METHOD_GET_SUMMARY_DASHBOARD = "GetSummaryDashboard"
METHOD_LIST_SNAPSHOTS = "ListSnapshots"
METHOD_LIST_SNAPSHOT_FILES = "ListSnapshotFiles"
METHOD_BACKUP = "Backup"
METHOD_DO_REPO_TASK = "DoRepoTask"
METHOD_FORGET = "Forget"
METHOD_RESTORE = "Restore"
METHOD_CANCEL = "Cancel"
METHOD_GET_LOGS = "GetLogs"
METHOD_RUN_COMMAND = "RunCommand"
METHOD_GET_DOWNLOAD_URL = "GetDownloadURL"
METHOD_CLEAR_HISTORY = "ClearHistory"
METHOD_PATH_AUTOCOMPLETE = "PathAutocomplete"
METHOD_SETUP_SFTP = "SetupSftp"

# Repo task types (DoRepoTask)
TASK_PRUNE = "TASK_PRUNE"
TASK_CHECK = "TASK_CHECK"
TASK_STATS = "TASK_STATS"
TASK_UNLOCK = "TASK_UNLOCK"
TASK_INDEX_SNAPSHOTS = "TASK_INDEX_SNAPSHOTS"

# Operation status values
OP_STATUS_UNKNOWN = "STATUS_UNKNOWN"
OP_STATUS_PENDING = "STATUS_PENDING"
OP_STATUS_INPROGRESS = "STATUS_INPROGRESS"
OP_STATUS_SUCCESS = "STATUS_SUCCESS"
OP_STATUS_WARNING = "STATUS_WARNING"
OP_STATUS_ERROR = "STATUS_ERROR"
OP_STATUS_SYSTEM_CANCELLED = "STATUS_SYSTEM_CANCELLED"
OP_STATUS_USER_CANCELLED = "STATUS_USER_CANCELLED"

OP_STATUSES_RUNNING = {OP_STATUS_PENDING, OP_STATUS_INPROGRESS}
OP_STATUSES_FINISHED = {
    OP_STATUS_SUCCESS,
    OP_STATUS_WARNING,
    OP_STATUS_ERROR,
    OP_STATUS_SYSTEM_CANCELLED,
    OP_STATUS_USER_CANCELLED,
}
OP_STATUSES_FAILED = {OP_STATUS_ERROR, OP_STATUS_WARNING}

# HA event names fired on the event bus
EVENT_BACKUP_STARTED = f"{DOMAIN}_backup_started"
EVENT_BACKUP_COMPLETED = f"{DOMAIN}_backup_completed"
EVENT_BACKUP_FAILED = f"{DOMAIN}_backup_failed"
EVENT_CONNECTION_LOST = f"{DOMAIN}_connection_lost"
EVENT_CONNECTION_RESTORED = f"{DOMAIN}_connection_restored"

# Runtime data key stored in hass.data
RUNTIME_DATA_COORDINATOR = "coordinator"
RUNTIME_DATA_API = "api"
RUNTIME_DATA_AUTH = "auth"

# Sensor / entity key suffixes
# Instance
KEY_REPO_COUNT = "repo_count"
KEY_PLAN_COUNT = "plan_count"
KEY_ACTIVE_OPERATIONS = "active_operations"
KEY_CONNECTED = "connected"

# Repo
KEY_SNAPSHOT_COUNT = "snapshot_count"
KEY_TOTAL_SIZE = "total_size"
KEY_UNCOMPRESSED_SIZE = "uncompressed_size"
KEY_COMPRESSION_RATIO = "compression_ratio"

# Plan
KEY_LAST_BACKUP_TIME = "last_backup_time"
KEY_LAST_BACKUP_STATUS = "last_backup_status"
KEY_BACKUP_DURATION = "backup_duration"
KEY_BYTES_ADDED = "bytes_added"
KEY_FILES_NEW = "files_new"
KEY_BYTES_ADDED_30D = "bytes_added_30d"
KEY_BACKUP_COUNT_30D = "backup_count_30d"
KEY_FAILURE_COUNT_30D = "failure_count_30d"
KEY_NEXT_BACKUP = "next_backup"
KEY_HOURS_SINCE_BACKUP = "hours_since_backup"
KEY_IS_RUNNING = "is_running"
KEY_BACKUP_STALE = "backup_stale"
KEY_LAST_BACKUP_FAILED = "last_backup_failed"

# Button keys
KEY_BTN_TRIGGER_BACKUP = "trigger_backup"
KEY_BTN_FORGET = "forget_snapshots"
KEY_BTN_PRUNE = "run_prune"
KEY_BTN_CHECK = "run_check"
KEY_BTN_STATS = "refresh_stats"
KEY_BTN_UNLOCK = "unlock_repo"

# Service names
SERVICE_TRIGGER_BACKUP = "trigger_backup"
SERVICE_CANCEL_OPERATION = "cancel_operation"
SERVICE_RUN_REPO_TASK = "run_repo_task"
SERVICE_FORGET_SNAPSHOTS = "forget_snapshots"
SERVICE_LIST_SNAPSHOTS = "list_snapshots"
SERVICE_SET_STALE_THRESHOLD = "set_stale_threshold"

# Device identifiers
def repo_device_id(entry_id: str, repo_id: str) -> str:
    return f"{entry_id}_repo_{repo_id}"

def plan_device_id(entry_id: str, plan_id: str) -> str:
    return f"{entry_id}_plan_{plan_id}"
