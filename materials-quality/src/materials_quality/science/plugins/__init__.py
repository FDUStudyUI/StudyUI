"""Optional materials-science solver plugins with graceful degradation."""

from .pybamm_battery import (
    SUPPORTED_MODELS,
    evaluate_operating_boundaries,
    pybamm_available,
    simulate_single_cell_discharge,
)
from .pymatgen_xrd import (
    XRD_LIMITATION_NOTICE,
    compute_theoretical_xrd_from_cif,
    match_measured_xrd_peaks,
    pymatgen_available,
)

__all__ = [
    "SUPPORTED_MODELS",
    "XRD_LIMITATION_NOTICE",
    "compute_theoretical_xrd_from_cif",
    "evaluate_operating_boundaries",
    "match_measured_xrd_peaks",
    "pybamm_available",
    "pymatgen_available",
    "simulate_single_cell_discharge",
]
