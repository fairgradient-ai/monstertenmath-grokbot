"""Channels: one module per platform. Instagram first; the engine talks only to the Channel protocol."""

from .base import Channel

__all__ = ["Channel"]
