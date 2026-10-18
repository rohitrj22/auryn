"""A tiny verdict harness for the proof scripts.

Each proof states one judging criterion, makes its checks, prints the numbers
behind each verdict, and exits non-zero on any failure. A judge should never
have to take a PASS on trust.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

GREEN, RED, DIM, BOLD, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
WIDTH = 74


@dataclass
class Proof:
    name: str
    criterion: str
    checks: list[tuple[bool, str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def start(self) -> Proof:
        print(f"\n{'─' * WIDTH}")
        print(f"  {BOLD}{self.name}{OFF}")
        print(f"  {DIM}criterion: {self.criterion}{OFF}")
        print(f"{'─' * WIDTH}")
        return self

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((bool(ok), label, detail))
        mark = f"{GREEN}ok  {OFF}" if ok else f"{RED}FAIL{OFF}"
        print(f"  {mark}  {label}")
        if detail:
            print(f"        {DIM}{detail}{OFF}")
        return bool(ok)

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  {DIM}·     {text}{OFF}")

    def verdict(self) -> int:
        failed = [c for c in self.checks if not c[0]]
        print(f"{'─' * WIDTH}")
        if failed:
            print(f"  {RED}{BOLD}FAIL{OFF}  {self.name}   "
                  f"{len(failed)} of {len(self.checks)} checks failed")
            for _, label, _ in failed:
                print(f"        {RED}-{OFF} {label}")
        else:
            print(f"  {GREEN}{BOLD}PASS{OFF}  {self.name}   "
                  f"{len(self.checks)} checks")
        print(f"{'─' * WIDTH}\n")
        return 1 if failed else 0


def finish(proof: Proof) -> None:
    sys.exit(proof.verdict())
