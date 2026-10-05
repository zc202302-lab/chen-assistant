from dataclasses import dataclass

class AutomationError(RuntimeError):
    """A pre-submit page or field could not be matched safely."""


class UncertainSubmission(AutomationError):
    """The final submit was clicked but the system did not confirm its outcome."""


@dataclass(frozen=True)
class MemberTask:
    row_number: int
    service_number: str
    group_search: str


