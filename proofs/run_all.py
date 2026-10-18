"""Run every proof and return one exit code.

    uv run python -m proofs.run_all

p0 is deliberately excluded: it requires FalkorDB to be stopped, which would
break every other proof. Run it on its own.
"""

from __future__ import annotations

import subprocess
import sys
import time

PROOFS = (
    ("p1", "persistence", "proofs.p1_persistence", []),
    ("p2", "memory kinds", "proofs.p2_memory_kinds", []),
    ("p3", "handoff", "proofs.p3_handoff", []),
    ("p4", "tenant isolation", "proofs.p4_isolation", ["--tenants", "200", "--probes", "400"]),
    ("p6", "shared state", "proofs.p6_shared_state", []),
    ("p5", "concurrency", "proofs.p5_concurrency", ["--seconds", "10"]),
)

GREEN, RED, DIM, BOLD, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def main() -> None:
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    print(f"\n{BOLD}  Auryn — the five Track 02 criteria, as runnable proofs{OFF}")
    print(f"  {DIM}no credentials required{OFF}\n")

    results = []
    for tag, label, module, extra in PROOFS:
        t0 = time.perf_counter()
        proc = subprocess.run([sys.executable, "-m", module, *extra],
                              capture_output=not verbose, text=True)
        took = time.perf_counter() - t0
        ok = proc.returncode == 0
        results.append((tag, label, ok, took, proc.stdout if not verbose else ""))
        mark = f"{GREEN}PASS{OFF}" if ok else f"{RED}FAIL{OFF}"
        print(f"  {tag}  {label:.<36} {mark}  {DIM}{took:5.1f}s{OFF}")
        if not ok and not verbose:
            for line in (proc.stdout or "").splitlines():
                if "FAIL" in line:
                    print(f"        {line.strip()}")

    passed = sum(1 for *_, ok, _, _ in [(r[0], r[1], r[2], r[3], r[4]) for r in results] if ok)
    total = len(results)
    print()
    if passed == total:
        print(f"  {GREEN}{BOLD}{passed}/{total} passed{OFF}")
    else:
        print(f"  {RED}{BOLD}{passed}/{total} passed{OFF}")
    print(f"  {DIM}p0 (the graph does real work) runs separately; it needs "
          f"FalkorDB stopped{OFF}\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
