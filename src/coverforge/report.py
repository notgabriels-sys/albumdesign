"""Result and report data structures plus their textual rendering."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Status(enum.Enum):
    """Outcome of a single check, ordered by increasing severity."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"

    @property
    def severity(self) -> int:
        return {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}[self]


# Plain markers plus the ANSI colour to wrap them in when writing to a TTY.
_MARKERS = {
    Status.PASS: ("PASS", "32"),  # green
    Status.WARN: ("WARN", "33"),  # yellow
    Status.FAIL: ("FAIL", "31"),  # red
}


@dataclass(frozen=True)
class Result:
    """The outcome of one named check."""

    check: str
    status: Status
    message: str

    def render(self, color: bool = False) -> str:
        marker, code = _MARKERS[self.status]
        if color:
            marker = f"\033[1;{code}m{marker}\033[0m"
        return f"  [{marker}] {self.check}: {self.message}"


@dataclass
class Report:
    """A collection of results for a single cover image."""

    path: str
    profile: str = "default"
    results: list[Result] = field(default_factory=list)

    def add(self, check: str, status: Status, message: str) -> Result:
        result = Result(check=check, status=status, message=message)
        self.results.append(result)
        return result

    @property
    def worst(self) -> Status:
        """The most severe status across all results (PASS if empty)."""
        return max((r.status for r in self.results), key=lambda s: s.severity, default=Status.PASS)

    @property
    def ok(self) -> bool:
        """True when nothing failed (warnings are allowed)."""
        return self.worst is not Status.FAIL

    def counts(self) -> dict[Status, int]:
        counts = {Status.PASS: 0, Status.WARN: 0, Status.FAIL: 0}
        for result in self.results:
            counts[result.status] += 1
        return counts

    def render(self, color: bool = False) -> str:
        header = self.path
        if self.profile and self.profile != "default":
            header = f"{header}  (profile: {self.profile})"
        lines = [header]
        lines.extend(result.render(color=color) for result in self.results)
        counts = self.counts()
        lines.append(
            "  "
            f"{counts[Status.PASS]} passed, "
            f"{counts[Status.WARN]} warning(s), "
            f"{counts[Status.FAIL]} failed"
        )
        return "\n".join(lines)
