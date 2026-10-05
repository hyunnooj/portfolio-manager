from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class RagResult:
    status: Literal["DISABLED", "UNAVAILABLE"]
    enabled: bool


class RagGateway(Protocol):
    def status(self) -> RagResult: ...
    def search(self, query: str) -> RagResult: ...


class DeferredRagGateway:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def status(self) -> RagResult:
        return RagResult("UNAVAILABLE" if self.enabled else "DISABLED", self.enabled)

    def search(self, query: str) -> RagResult:
        return self.status()
