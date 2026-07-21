"""Fixture InstrumentContext."""

from __future__ import annotations

from typing import Any, Optional


def requires_version(major: int, minor: int):  # noqa: ANN201
    def decorator(func):  # noqa: ANN001, ANN202
        return func

    return decorator


class InstrumentContext:
    """A pipette context used in protocols."""

    @requires_version(2, 0)
    def aspirate(
        self,
        volume: Optional[float] = None,
        location: Any = None,
        rate: float = 1.0,
    ) -> InstrumentContext:
        """Aspirate liquid.

        Args:
            volume: Volume in microliters.
            location: Well or location.
            rate: Speed multiplier.
        """
        return self

    def transfer(self, volume: float, source: Any, dest: Any) -> InstrumentContext:
        """Transfer liquid from source to destination."""
        return self


DEPRECATED_FLAG = True
