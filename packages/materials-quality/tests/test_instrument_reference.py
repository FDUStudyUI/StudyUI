import numpy as np

from scripts.evaluate_material_instruments import reference_peaks


def test_reference_does_not_misidentify_a_monotonic_edge_background_as_a_peak():
    x = np.arange(9)
    y = np.array([100, 50, 0, 10, 10, 10, 0, 4, 0])
    assert reference_peaks(x, y, 5) == [4.0]
    assert reference_peaks(x, y, 11) == []
    assert reference_peaks(x, y + 900, 5) == [4.0]
    assert reference_peaks(x, y * 2, 10) == [4.0]
