"""Protocol boundary between Q3-C transport search and Q3-B relay decoder."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class RelayDecoderProtocol(ABC):
    @abstractmethod
    def decode_relay_schedule(self, transport_state: Any, transport_schedule: Any, *, dt_s: float = 2.0):
        raise NotImplementedError


class RelayDecoderStub(RelayDecoderProtocol):
    """Test-only stand-in. It is never used by a formal solver path."""
    def __init__(self, result: Mapping[str, Any] | None = None):
        self.result = dict(result or {"status": "PASS", "checks": {"stub": True}, "metrics": {}})

    def decode_relay_schedule(self, transport_state: Any, transport_schedule: Any, *, dt_s: float = 2.0):
        return self.result


class Q3BRelayDecoderAdapter(RelayDecoderProtocol):
    """Lazy adapter; importing it does not execute Q3-B or create results."""
    def __init__(self, decoder_function):
        self.decoder_function = decoder_function

    def decode_relay_schedule(self, transport_state: Any, transport_schedule: Any, *, dt_s: float = 2.0):
        return self.decoder_function(transport_state, transport_schedule, dt_s=dt_s)
