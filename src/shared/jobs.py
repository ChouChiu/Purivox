from __future__ import annotations

SIGMA_CHOICES: tuple[int, ...] = (1, 3, 8, 16)
STRENGTH_MINIMUM = 0
STRENGTH_MAXIMUM = 100
STRENGTH_RANGE = range(STRENGTH_MINIMUM, STRENGTH_MAXIMUM + 1)


def validate_reference_settings(strength: int, sigma: int) -> None:
    """Check the settings every reference-cancellation job shares.

    Single-song and full-stage jobs live in feature packages that must not
    import one another, and the CLI offers the same options again, so the
    accepted values are defined once here instead of three times.
    """
    if not STRENGTH_MINIMUM <= strength <= STRENGTH_MAXIMUM:
        raise ValueError(f"strength must be in [{STRENGTH_MINIMUM}, {STRENGTH_MAXIMUM}]")
    if sigma not in SIGMA_CHOICES:
        raise ValueError("sigma must be one of " + ", ".join(str(value) for value in SIGMA_CHOICES))
