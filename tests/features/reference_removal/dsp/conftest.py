import numpy as np
import pytest


@pytest.fixture(scope="module")
def scene():
    """Three seconds of a two-tone vocal over a two-tone instrumental."""
    sample_rate = 22_050
    time = np.arange(sample_rate * 3) / sample_rate
    vocal = 0.5 * np.sin(2 * np.pi * 440 * time) + 0.2 * np.sin(2 * np.pi * 880 * time)
    instrumental = 0.4 * np.sin(2 * np.pi * 110 * time) + 0.1 * np.sin(2 * np.pi * 220 * time)
    return sample_rate, vocal, instrumental, vocal + instrumental
