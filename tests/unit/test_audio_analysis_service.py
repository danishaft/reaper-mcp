import struct
import wave
from pathlib import Path

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse
from reaper_mcp.services.audio_analysis_service import AudioAnalysisService


class FakeBridgeClient:
    def __init__(self, response: BridgeResponse) -> None:
        self.response = response
        self.command: str | None = None
        self.args: dict | None = None

    async def execute(
        self,
        command: str,
        args: dict | None = None,
        options: object | None = None,
    ) -> BridgeResponse:
        self.command = command
        self.args = args
        return self.response


def _write_stereo_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(1000)
        wav_file.writeframes(
            b"".join(
                struct.pack("<hh", left, right)
                for left, right in ((0, 0), (16384, 16384), (-16384, -16384))
            )
        )


async def test_analyze_file_returns_basic_metrics(tmp_path: Path) -> None:
    audio_path = tmp_path / "loop.wav"
    _write_stereo_wav(audio_path)

    result = await AudioAnalysisService([tmp_path]).analyze_file(str(audio_path))

    assert result["ok"] is True
    analysis = result["analysis"]
    assert analysis["channels"] == 2
    assert analysis["sample_rate"] == 1000
    assert analysis["frame_count"] == 3
    assert analysis["duration_seconds"] == 0.003
    assert analysis["clipping_samples"] == 0
    assert analysis["stereo_correlation"] == 1.0
    assert analysis["unsupported_metrics"] == [
        "integrated_lufs",
        "true_peak_dbfs",
    ]


async def test_analyze_file_rejects_path_outside_allowed_roots(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "loop.wav"
    _write_stereo_wav(audio_path)

    result = await AudioAnalysisService([]).analyze_file(str(audio_path))

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.AUDIO_PATH_NOT_ALLOWED


async def test_analyze_file_rejects_non_wav_file(tmp_path: Path) -> None:
    audio_path = tmp_path / "loop.mp3"
    audio_path.write_bytes(b"not audio")

    result = await AudioAnalysisService([tmp_path]).analyze_file(str(audio_path))

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.AUDIO_PATH_NOT_ALLOWED


async def test_calculate_take_loudness_returns_reaper_stats() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "take_guid": "{TAKE-GUID}",
                "calculation_status": 1,
                "render_stats": "file.wav;-14.0;-1.0",
                "render_stats_summary": "LUFS-I -14.0;True peak -1.0",
            },
        )
    )

    result = await AudioAnalysisService(bridge_client=bridge).calculate_take_loudness(
        "{TAKE-GUID}"
    )

    assert result["ok"] is True
    assert bridge.command == "calculate_take_loudness"
    assert bridge.args == {"take_guid": "{TAKE-GUID}"}
    assert result["calculation_status"] == 1
    assert result["render_stats_summary"] == "LUFS-I -14.0;True peak -1.0"
