from __future__ import annotations

from typing import Protocol

from ..models import DiscoveryBundle, ExtractionAttempt


class Extractor(Protocol):
    mode_name: str

    def run(self, bundle: DiscoveryBundle) -> ExtractionAttempt:
        ...
