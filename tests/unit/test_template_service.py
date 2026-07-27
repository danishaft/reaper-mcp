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
