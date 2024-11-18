try:
    from ._version import __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"

__all__ = ("__version__",)
