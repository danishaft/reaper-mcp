from hashlib import sha256
from pathlib import Path

from reaper_mcp.models.bridge import BridgeResponse
from reaper_mcp.services.template_service import TemplateService


class FakeBridgeClient:
    def __init__(self, response: BridgeResponse) -> None:
        self.response = response
        self.command: str | None = None

    async def execute(
        self,
        command: str,
        args: dict | None = None,
        options: object | None = None,
    ) -> BridgeResponse:
        self.command = command
        return self.response


async def test_template_service_denies_path_outside_configured_root(
    tmp_path: Path,
) -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = TemplateService(bridge, [tmp_path / "templates"])

    result = await service.apply_template(str(tmp_path / "other.RTrackTemplate"))

    assert bridge.command is None
    assert result["error"]["code"] == "template_path_not_allowed"


async def test_template_service_lists_templates(tmp_path: Path) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    (template_root / "Vocal.RTrackTemplate").write_text("<TRACK>")
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await TemplateService(bridge, [template_root]).list_templates()

    assert result["template_count"] == 1
    assert result["templates"][0]["name"] == "Vocal"
    assert result["templates"][0]["sha256"] == sha256(b"<TRACK>").hexdigest()


async def test_template_service_does_not_hash_symlink_outside_allowed_root(
    tmp_path: Path,
) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    outside_template = tmp_path / "Outside.RTrackTemplate"
    outside_template.write_text("<TRACK>")
    (template_root / "Linked.RTrackTemplate").symlink_to(outside_template)
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await TemplateService(bridge, [template_root]).list_templates()

    assert result["templates"] == []
    assert result["template_count"] == 0


async def test_template_service_requires_matching_hash_before_deletion(
    tmp_path: Path,
) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    template_path = template_root / "Vocal.RTrackTemplate"
    template_path.write_text("<TRACK>")
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = TemplateService(bridge, [template_root])

    conflict = await service.delete_template(template_path.as_posix(), "0" * 64)

    assert conflict["error"]["code"] == "template_conflict"
    assert template_path.is_file()

    deleted = await service.delete_template(
        template_path.as_posix(), sha256(b"<TRACK>").hexdigest()
    )

    assert deleted["ok"] is True
    assert deleted["deleted_sha256"] == sha256(b"<TRACK>").hexdigest()
    assert not template_path.exists()
