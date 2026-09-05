import pytest

from entrypoints.cli import build_parser
from shared.jobs import OutputTracks


def test_reference_command_parses_its_settings():
    parser = build_parser()
    assert parser.prog == "purivox"

    defaults = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav"])
    assert defaults.sigma == 3
    assert defaults.align

    custom = parser.parse_args(
        ["mr", "song.wav", "reference.flac", "output.wav", "--sigma", "8", "--no-align"]
    )
    assert custom.sigma == 8
    assert not custom.align


def test_reference_command_parses_the_export_choice():
    parser = build_parser()

    defaults = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav"])
    assert defaults.tracks is OutputTracks.VOCAL

    both = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav", "--tracks", "both"])
    assert both.tracks is OutputTracks.BOTH


def test_reference_command_rejects_an_unknown_export_choice():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["mr", "song.wav", "reference.flac", "out.wav", "--tracks", "nope"])
