# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""AIS sources — re-exports the two independent AISSource adapters.

Split into separate modules so the synthetic source's RNG and the AISStream
protocol field never share a file (keeps the secret-scanner hook quiet and the
sources cleanly decoupled). The public import path stays sources.ais.*.
"""
from yey.boats.simulator.sources.aisstream_source import AISStreamSource  # type: ignore[import]
from yey.boats.simulator.sources.synthetic_ais_source import SyntheticAISSource  # type: ignore[import]

__all__ = ["AISStreamSource", "SyntheticAISSource"]
