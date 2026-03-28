"""Async HTTP client for the Backrest Connect RPC API."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

from .auth import BackrestAuthManager, BackrestAuthError, BackrestCannotConnectError
from .const import (
    AUTH_SERVICE_PATH,
    BACKREST_SERVICE_PATH,
    DEFAULT_TIMEOUT,
    METHOD_BACKUP,
    METHOD_CANCEL,
    METHOD_CLEAR_HISTORY,
    METHOD_DO_REPO_TASK,
    METHOD_FORGET,
    METHOD_GET_CONFIG,
    METHOD_GET_OPERATIONS,
    METHOD_GET_SUMMARY_DASHBOARD,
    METHOD_LIST_SNAPSHOTS,
    METHOD_PATH_AUTOCOMPLETE,
    METHOD_RESTORE,
    METHOD_RUN_COMMAND,
    METHOD_SETUP_SFTP,
    TASK_CHECK,
    TASK_PRUNE,
    TASK_STATS,
    TASK_UNLOCK,
)

_LOGGER = logging.getLogger(__name__)


class BackrestServerError(Exception):
    """Raised on 5xx responses from Backrest."""


class BackrestApiClient:
    """Thin async wrapper around all Backrest Connect RPC endpoints.

    Uses Connect JSON mode (Content-Type: application/json) so no
    protobuf library is required — plain aiohttp + dicts.
    """

    def __init__(
        self,
        base_url: str,
        auth_manager: BackrestAuthManager,
        session: aiohttp.ClientSession,
        timeout: int = DEFAULT_TIMEOUT,
        verify_ssl: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth_manager
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        # None = default SSL verification; False = skip (self-signed certs)
        self._ssl: bool | None = None if verify_ssl else False

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        service: str,
        method: str,
        body: Optional[dict] = None,
    ) -> Any:
        """POST to a Connect RPC endpoint and return the parsed JSON response.

        Handles:
        - Bearer token injection
        - Automatic retry once on 401 (token refresh)
        - Error mapping to typed exceptions
        """
        url = f"{self._base_url}/{service}/{method}"
        payload = body or {}

        for attempt in range(2):
            token = await self._auth.get_token()
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            try:
                async with self._session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                    ssl=self._ssl,
                ) as resp:
                    if resp.status == 401:
                        if attempt == 0:
                            # Invalidate cached token and retry once
                            _LOGGER.debug(
                                "Got 401 from %s, refreshing token and retrying", url
                            )
                            await self._auth.invalidate_token()
                            continue
                        raise BackrestAuthError(
                            f"Authentication failed for {url} after token refresh"
                        )

                    if resp.status >= 500:
                        text = await resp.text()
                        raise BackrestServerError(
                            f"Backrest server error {resp.status}: {text}"
                        )

                    if resp.status >= 400:
                        text = await resp.text()
                        raise BackrestServerError(
                            f"Backrest request error {resp.status}: {text}"
                        )

                    # 204 No Content or empty body
                    if resp.status == 204 or resp.content_length == 0:
                        return {}

                    return await resp.json(content_type=None)

            except aiohttp.ClientConnectorError as err:
                raise BackrestCannotConnectError(
                    f"Cannot connect to Backrest at {self._base_url}"
                ) from err
            except asyncio.TimeoutError as err:
                raise BackrestCannotConnectError(
                    f"Request to {url} timed out"
                ) from err

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    async def get_config(self) -> dict:
        """Fetch the full Backrest configuration (repos, plans, auth, etc.)."""
        return await self._request(BACKREST_SERVICE_PATH, METHOD_GET_CONFIG)

    async def set_config(self, config: dict) -> dict:
        """Update the Backrest configuration."""
        return await self._request(BACKREST_SERVICE_PATH, "SetConfig", config)

    # ------------------------------------------------------------------
    # Dashboard & Operations
    # ------------------------------------------------------------------

    async def get_summary_dashboard(self) -> dict:
        """Fetch the summary dashboard (per-plan/repo stats, charts)."""
        return await self._request(BACKREST_SERVICE_PATH, METHOD_GET_SUMMARY_DASHBOARD)

    async def get_operations(
        self,
        repo_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        instance_id: Optional[str] = None,
        only_last: Optional[int] = None,
        flow_id: Optional[int] = None,
    ) -> dict:
        """Query operation history with optional filters.

        Args:
            repo_id: Filter by repository ID.
            plan_id: Filter by plan ID.
            instance_id: Filter by instance ID.
            only_last: Return only the last N operations.
            flow_id: Filter by flow/group ID.
        """
        selector: dict = {}
        if repo_id:
            selector["repoId"] = repo_id
        if plan_id:
            selector["planId"] = plan_id
        if instance_id:
            selector["instanceId"] = instance_id
        if flow_id:
            selector["flowId"] = flow_id

        body: dict = {}
        if selector:
            body["selector"] = selector
        if only_last is not None:
            body["lastN"] = only_last

        return await self._request(BACKREST_SERVICE_PATH, METHOD_GET_OPERATIONS, body)

    async def get_inprogress_operations(self) -> dict:
        """Get all currently running (INPROGRESS/PENDING) operations."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_GET_OPERATIONS,
            {"selector": {}, "filterStatus": ["STATUS_INPROGRESS", "STATUS_PENDING"]},
        )

    async def clear_history(
        self,
        repo_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        only_failed: bool = False,
    ) -> dict:
        """Clear operation history records."""
        body: dict = {}
        selector: dict = {}
        if repo_id:
            selector["repoId"] = repo_id
        if plan_id:
            selector["planId"] = plan_id
        if selector:
            body["selector"] = selector
        if only_failed:
            body["onlyFailed"] = True
        return await self._request(BACKREST_SERVICE_PATH, METHOD_CLEAR_HISTORY, body)

    # ------------------------------------------------------------------
    # Backup actions
    # ------------------------------------------------------------------

    async def trigger_backup(self, plan_id: str) -> dict:
        """Trigger a backup for the given plan."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_BACKUP,
            {"planId": plan_id},
        )

    async def forget_snapshots(self, plan_id: str, repo_id: str) -> dict:
        """Apply retention policy (forget old snapshots) for a plan."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_FORGET,
            {"planId": plan_id, "repoId": repo_id},
        )

    async def restore_snapshot(
        self,
        snapshot_id: str,
        repo_id: str,
        path: str,
        target: str,
    ) -> dict:
        """Restore a snapshot or a path within it to a target directory."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_RESTORE,
            {
                "snapshotId": snapshot_id,
                "repoId": repo_id,
                "path": path,
                "target": target,
            },
        )

    async def cancel_operation(self, operation_id: int) -> dict:
        """Cancel a running operation by its ID."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_CANCEL,
            {"value": operation_id},
        )

    # ------------------------------------------------------------------
    # Repo tasks
    # ------------------------------------------------------------------

    async def do_repo_task(self, repo_id: str, task: str) -> dict:
        """Execute a maintenance task on a repository.

        task: one of TASK_PRUNE, TASK_CHECK, TASK_STATS, TASK_UNLOCK
        """
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_DO_REPO_TASK,
            {"repoId": repo_id, "task": task},
        )

    async def run_prune(self, repo_id: str) -> dict:
        """Run prune on a repository."""
        return await self.do_repo_task(repo_id, TASK_PRUNE)

    async def run_check(self, repo_id: str) -> dict:
        """Run integrity check on a repository."""
        return await self.do_repo_task(repo_id, TASK_CHECK)

    async def run_stats(self, repo_id: str) -> dict:
        """Refresh repository statistics."""
        return await self.do_repo_task(repo_id, TASK_STATS)

    async def unlock_repo(self, repo_id: str) -> dict:
        """Unlock a locked repository."""
        return await self.do_repo_task(repo_id, TASK_UNLOCK)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def list_snapshots(
        self,
        repo_id: str,
        plan_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> dict:
        """List snapshots for a repository, optionally filtered by plan or tag."""
        body: dict = {"repoId": repo_id}
        if plan_id:
            body["planId"] = plan_id
        if tag:
            body["tag"] = tag
        return await self._request(BACKREST_SERVICE_PATH, METHOD_LIST_SNAPSHOTS, body)

    async def list_snapshot_files(
        self, repo_id: str, snapshot_id: str, path: str = "/"
    ) -> dict:
        """List files within a snapshot at the given path."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            "ListSnapshotFiles",
            {"repoId": repo_id, "snapshotId": snapshot_id, "path": path},
        )

    async def get_download_url(
        self, repo_id: str, snapshot_id: str, path: str
    ) -> dict:
        """Get a signed download URL for a file in a snapshot."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            "GetDownloadURL",
            {"repoId": repo_id, "snapshotId": snapshot_id, "path": path},
        )

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    async def run_command(self, repo_id: str, command: str) -> dict:
        """Run an arbitrary restic command on a repository."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_RUN_COMMAND,
            {"repoId": repo_id, "command": command},
        )

    async def path_autocomplete(self, path: str) -> dict:
        """List directory contents on the Backrest server for path autocomplete."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_PATH_AUTOCOMPLETE,
            {"value": path},
        )

    async def setup_sftp(
        self, host: str, user: str, port: int = 22
    ) -> dict:
        """Configure SFTP SSH key authentication."""
        return await self._request(
            BACKREST_SERVICE_PATH,
            METHOD_SETUP_SFTP,
            {"host": host, "user": user, "port": port},
        )
