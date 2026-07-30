"""Track-template service."""

from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.templates import (
    TrackTemplateList,
    TrackTemplateMutationResult,
    TrackTemplateSnapshot,
)


class TemplateService:
    """Expose guarded track-template file operations."""

    def __init__(
        self,
        bridge_client: BridgeClient,
        allowed_template_roots: list[Path] | None = None,
    ) -> None:
        self.bridge_client = bridge_client
        self.allowed_template_roots = [
            root.expanduser().resolve() for root in (allowed_template_roots or [])
        ]

    async def list_templates(self) -> dict[str, Any]:
        """List templates in configured roots."""

        templates: list[TrackTemplateSnapshot] = []
        for root in self.allowed_template_roots:
            if not root.is_dir():
                continue
            for candidate in sorted(root.glob("*.RTrackTemplate")):
                path = candidate.resolve(strict=False)
                if not path.is_relative_to(root) or not path.is_file():
                    continue
                try:
                    templates.append(
                        TrackTemplateSnapshot(
                            name=path.stem,
                            path=path,
                            sha256=self._file_sha256(path),
                        )
                    )
                except OSError:
                    continue
        result = TrackTemplateList(templates=templates, template_count=len(templates))
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": [],
        }

    async def save_template(
        self, track_guid: str, template_path: str
    ) -> dict[str, Any]:
        """Save one track's state chunk to an approved template path."""

        path_result = self._validate_path(template_path)
        if path_result is not None:
            return path_result
        path = Path(template_path).expanduser().resolve(strict=False)
        response = await self.bridge_client.execute(
            "save_track_template",
            args={"track_guid": track_guid, "template_path": str(path)},
            options=CommandOptions(
                mutates_project=False,
                undo_label=None,
            ),
        )
        return self._mutation_response(response)

    async def apply_template(
        self, template_path: str, index: int | None = None
    ) -> dict[str, Any]:
        """Apply one approved track template as a new track."""

        path_result = self._validate_path(template_path)
        if path_result is not None:
            return path_result
        path = Path(template_path).expanduser().resolve(strict=False)
        if not path.is_file():
            return self._path_error(path, "Track template file does not exist.")
        response = await self.bridge_client.execute(
            "apply_track_template",
            args={"template_path": str(path), "index": index},
            options=CommandOptions(
                mutates_project=True,
                undo_label="Apply track template",
            ),
        )
        return self._mutation_response(response)

    async def delete_template(
        self, template_path: str, expected_sha256: str
    ) -> dict[str, Any]:
        """Delete one approved track template when its content still matches."""

        path_result = self._validate_path(template_path)
        if path_result is not None:
            return path_result
        path = Path(template_path).expanduser().resolve(strict=False)
        if not path.is_file():
            return self._path_error(path, "Track template file does not exist.")
        actual_sha256 = self._file_sha256(path)
        if actual_sha256 != expected_sha256:
            return {
                "ok": False,
                "error": ErrorResponse(
                    code=ErrorCode.TEMPLATE_CONFLICT,
                    message="The track template changed after it was listed.",
                    details={
                        "template_path": str(path),
                        "expected_sha256": expected_sha256,
                        "actual_sha256": actual_sha256,
                    },
                    recoverable=True,
                    suggested_action=(
                        "List track templates again and confirm the current SHA-256 "
                        "before retrying deletion."
                    ),
                ).model_dump(mode="json"),
                "warnings": [],
            }
        path.unlink()
        return {
            "ok": True,
            "deleted_template_path": str(path),
            "deleted_sha256": actual_sha256,
            "warnings": [],
        }

    def _validate_path(self, template_path: str) -> dict[str, Any] | None:
        path = Path(template_path).expanduser().resolve(strict=False)
        if path.suffix.lower() != ".rtracktemplate":
            return self._path_error(path, "Track templates must use .RTrackTemplate.")
        if not any(path.is_relative_to(root) for root in self.allowed_template_roots):
            return self._path_error(path, "The template path is outside allowed roots.")
        if not path.parent.is_dir():
            return self._path_error(
                path, "The template parent directory does not exist."
            )
        return None

    def _mutation_response(self, response: BridgeResponse) -> dict[str, Any]:
        if not response.ok:
            return self._error_result(response)
        try:
            result = TrackTemplateMutationResult.model_validate(response.result or {})
        except ValidationError as exc:
            return {
                "ok": False,
                "error": ErrorResponse(
                    code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                    message="The Lua bridge returned an invalid template payload.",
                    details={"errors": exc.errors(include_context=False)},
                    recoverable=True,
                    suggested_action="Restart the Lua bridge and retry the command.",
                ).model_dump(mode="json"),
                "warnings": response.warnings,
            }
        payload = {
            "ok": True,
            "template_path": str(result.template_path),
            "track_count": result.track_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }
        if result.track is not None:
            payload["track"] = result.track.model_dump(mode="json")
        return payload

    def _error_result(self, response: BridgeResponse) -> dict[str, Any]:
        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }

    def _path_error(self, path: Path, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": ErrorCode.TEMPLATE_PATH_NOT_ALLOWED,
                "message": message,
                "details": {"template_path": str(path)},
                "recoverable": True,
                "suggested_action": (
                    "Choose a .RTrackTemplate path inside "
                    "REAPER_MCP_ALLOWED_TEMPLATE_ROOTS."
                ),
            },
            "warnings": [],
        }

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as template_file:
            for chunk in iter(lambda: template_file.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
