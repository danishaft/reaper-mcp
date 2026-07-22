from reaper_mcp.models.position import (
    MusicalLength,
    MusicalPosition,
    musical_position_to_qn,
    musical_range_to_qn,
)


def test_musical_position_to_qn_is_one_based() -> None:
    position = MusicalPosition(measure=2, beat=1)

    assert musical_position_to_qn(position, beats_per_measure=4) == 4


def test_musical_range_to_qn_uses_length_beats() -> None:
    position = MusicalPosition(measure=3, beat=2)
    length = MusicalLength(beats=8)

    assert musical_range_to_qn(position, length, beats_per_measure=4) == (9, 17)
