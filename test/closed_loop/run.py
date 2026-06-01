#!/usr/bin/env python3
"""Closed-loop live test runner.

Usage (from repo root):
  python3 -m test.closed_loop.run --tier A
  python3 -m test.closed_loop.run --tier B
  python3 -m test.closed_loop.run --scenario shell_roundtrip
  python3 -m test.closed_loop.run --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from test.closed_loop.harness import DEFAULT_PORT, cdp_is_up, set_verbose
from test.closed_loop.pipeline_assert import PipelineFailure
from test.closed_loop.scenarios.tier_a import TIER_A
from test.closed_loop.scenarios.tier_b import TIER_B
from test.closed_loop.scenarios.rerun_latest import run_rerun_latest
from test.closed_loop.scenarios.dom_audit import run_dom_audit

ALL = {
    **TIER_A,
    **TIER_B,
    "rerun_latest": run_rerun_latest,
    "dom_audit": run_dom_audit,
}

TIER_MAP = {
    "A": ["smoke", "loop_no_rerun", "load_historical_skip", "synthetic_happy", "dom_audit"],
    "B": ["shell_roundtrip", "file_roundtrip", "agent_chain"],
    "C": ["rerun_latest"],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Gemini Chrome Agent closed-loop tests")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--tier", choices=["A", "B", "C", "all"], default=None)
    parser.add_argument("--scenario", choices=sorted(ALL.keys()), default=None)
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print timestamped progress steps to stdout",
    )
    args = parser.parse_args()

    if args.list:
        for tier, names in TIER_MAP.items():
            print(f"Tier {tier}:")
            for n in names:
                print(f"  {n}")
        return 0

    if not cdp_is_up(args.port):
        print(f"FAIL: CDP :{args.port} not up. Run: ./scripts/launch-debug-brave.sh", file=sys.stderr)
        return 1

    if args.scenario:
        scenarios = [args.scenario]
    elif args.tier == "all":
        scenarios = TIER_MAP["A"] + TIER_MAP["B"] + TIER_MAP["C"]
    elif args.tier:
        scenarios = TIER_MAP[args.tier]
    else:
        scenarios = TIER_MAP["A"]

    set_verbose(args.verbose)

    failed = 0
    for name in scenarios:
        fn = ALL.get(name)
        if not fn:
            print(f"SKIP unknown scenario: {name}")
            failed += 1
            continue
        print(f"\n=== scenario: {name} ===")
        try:
            fn(args.port)
        except PipelineFailure as e:
            print(f"FAIL {name}: {e}", file=sys.stderr)
            failed += 1
        except Exception as e:
            print(f"FAIL {name}: {e}", file=sys.stderr)
            failed += 1

    print(f"\n{'=' * 40}\n{len(scenarios) - failed}/{len(scenarios)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
