from entrypoints.cli import build_parser


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
