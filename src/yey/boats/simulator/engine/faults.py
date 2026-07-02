# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Shared fault-injection state for diagnostic-signal modeling.

The simulator is healthy by default; a *fault* is an explicit, demo-driven
deviation that lets a downstream diagnostic fire against reproducible data.
`FaultState` is a tiny, pure registry of `{fault_id: {active, severity}}` that
the Engine holds and threads into each model's `tick()`.

Seeding:
  - At construction, from the env var ``SIM_FAULTS`` — a comma-separated list of
    fault ids to activate at boot (e.g. ``SIM_FAULTS="raw_water_blocked,alternator_belt"``).
  - At runtime, via the command path (``set_fault`` / ``clear_fault`` commands,
    intercepted in ``Engine.submit_command``), so a fault can be toggled live.

Every known fault defaults to clear (inactive, severity 0.0). Activating a fault
without an explicit severity uses ``DEFAULT_SEVERITY`` (full strength).
"""
from __future__ import annotations

import os
from collections.abc import Iterable

# Canonical fault ids. Each maps to one modeled deviation (see signalk_writer /
# the engine models for where each is consumed).
KNOWN_FAULTS: tuple[str, ...] = (
    "low_oil_pressure",   # propulsion.main.oilPressure drops toward 0
    "raw_water_blocked",  # exhaustTemperature + coolant rise at steady RPM
    "alternator_belt",    # alternator current -> 0 while running (+ coolant rise)
    "weak_starter",       # deep starter crank dip / slow voltage recovery
    "gps_degraded",       # sats down, HDOP up, quality -> no GNSS, position jitter
)

DEFAULT_SEVERITY = 1.0


class FaultState:
    """Mutable registry of injected faults. Pure data + simple setters."""

    def __init__(self, seed: Iterable[str] | None = None,
                 env_var: str = "SIM_FAULTS") -> None:
        # All known faults present, clear by default.
        self._faults: dict[str, dict] = {
            fid: {"active": False, "severity": 0.0} for fid in KNOWN_FAULTS
        }
        ids: list[str] = list(seed) if seed is not None else self._parse_env(env_var)
        for fid in ids:
            self.set(fid)

    @staticmethod
    def _parse_env(env_var: str) -> list[str]:
        raw = os.environ.get(env_var, "")
        return [tok.strip() for tok in raw.split(",") if tok.strip()]

    def set(self, fault_id: str, severity: float = DEFAULT_SEVERITY) -> None:
        """Activate a fault. Unknown ids are accepted (forward-compatible) but
        clamped severity keeps models well-behaved."""
        sev = max(0.0, min(1.0, float(severity)))
        self._faults[fault_id] = {"active": True, "severity": sev}

    def clear(self, fault_id: str) -> None:
        """Deactivate a fault (severity back to 0)."""
        self._faults[fault_id] = {"active": False, "severity": 0.0}

    def is_active(self, fault_id: str) -> bool:
        return bool(self._faults.get(fault_id, {}).get("active", False))

    def severity(self, fault_id: str) -> float:
        """Severity 0..1 if active, else 0.0."""
        f = self._faults.get(fault_id)
        return float(f["severity"]) if f and f["active"] else 0.0

    def active_ids(self) -> list[str]:
        return [fid for fid, f in self._faults.items() if f["active"]]

    def as_dict(self) -> dict[str, dict]:
        """Snapshot copy for inspection/serialisation."""
        return {fid: dict(f) for fid, f in self._faults.items()}
