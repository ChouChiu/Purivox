import pytest

from entrypoints.cli import build_parser


def test_reference_command_has_no_algorithm_option():
    parser = build_parser()
    assert parser.prog == "purivox"
    defaults = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav"])

    assert not hasattr(defaults, "algorithm")
    assert defaults.sigma == 3
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["mr", "song.wav", "reference.flac", "output.wav", "--algorithm", "direct"]
        )

    custom_sigma = parser.parse_args(
        ["mr", "song.wav", "reference.flac", "output.wav", "--sigma", "8"]
    )
    assert custom_sigma.sigma == 8


def test_reference_enhancement_switches_default_off_and_can_be_enabled():
    parser = build_parser()
    defaults = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav"])
    assert not defaults.center_extraction
    assert not defaults.weak_vocal_protection

    enabled = parser.parse_args(
        [
            "mr",
            "song.wav",
            "reference.flac",
            "output.wav",
            "--center-extraction",
            "--weak-vocal-protection",
        ]
    )
    assert enabled.center_extraction
    assert enabled.weak_vocal_protection


def test_reference_alignment_defaults_on_and_cli_can_disable_it():
    parser = build_parser()
    defaults = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav"])
    disabled = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav", "--no-align"])

    assert defaults.align
    assert not disabled.align
