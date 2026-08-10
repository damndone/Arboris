"""Stable errors for the standalone time-series kernels."""


class TimeSeriesPackError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


__all__ = ["TimeSeriesPackError"]
