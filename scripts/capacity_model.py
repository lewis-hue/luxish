#!/usr/bin/env python3
"""Reproduces every figure in docs/performance/capacity.md.

The tables in that document were first written by hand, and the peak factor got
applied twice — which overstated one scenario's token usage fourfold and produced the
wrong conclusion. This script exists so a changed assumption propagates instead of
being hand-edited into a table.

Provider limits and prices are the only verified inputs (dev.meta.ai, 2026-10-26).
Everything else is an assumption, named as such.

    python scripts/capacity_model.py
    python scripts/capacity_model.py --runs-per-dau 0.8   # sensitivity
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

SECONDS_PER_DAY = 86_400

# --- verified provider limits and prices -------------------------------------
# https://dev.meta.ai/docs/pricing-rate-limits — per TEAM, not per API key.
META_RPM_LIMIT = 3_000
META_TPM_LIMIT = 4_000_000
META_IMAGE_RPM_LIMIT = 150
SPARK_INPUT_PER_1M = 1.25
SPARK_OUTPUT_PER_1M = 4.25
SPARK_CONTRIB_INPUT_PER_1M = 0.10
SPARK_CONTRIB_OUTPUT_PER_1M = 0.20
SAM_PER_1000_IMAGES = 2.50

# --- cloud unit prices (assumed; list prices, no committed-use discount) -----
GCS_PER_GB_MONTH = 0.020
CDN_PER_GB = 0.08


@dataclass(frozen=True)
class Scenario:
    name: str
    registered: int
    mau: int
    dau: int


SCENARIOS = (
    Scenario("A Demo", 50, 45, 30),
    Scenario("B Private alpha", 2_000, 1_200, 500),
    Scenario("C Commercial launch", 200_000, 60_000, 18_000),
    Scenario("D Scale target", 5_000_000, 1_500_000, 450_000),
)


@dataclass(frozen=True)
class Assumptions:
    """Every one of these is a guess until measured."""

    requests_per_user_per_day: float = 35
    peak_factor: float = 4
    db_ops_per_request: float = 4
    runs_per_dau_per_day: float = 0.4
    service_seconds: float = 25
    model_calls_per_run: float = 4
    input_tokens_per_call: float = 8_000
    output_tokens_per_run: float = 1_500
    garments_per_user: float = 40
    mb_per_garment: float = 1.9
    image_loads_per_dau_per_day: float = 60
    kb_per_image: float = 120
    uploads_per_dau_per_day: float = 0.5


def tokens_per_run(a: Assumptions) -> float:
    return a.model_calls_per_run * a.input_tokens_per_call + a.output_tokens_per_run


def cost_per_run(a: Assumptions, *, contributor: bool = False) -> float:
    in_price = SPARK_CONTRIB_INPUT_PER_1M if contributor else SPARK_INPUT_PER_1M
    out_price = SPARK_CONTRIB_OUTPUT_PER_1M if contributor else SPARK_OUTPUT_PER_1M
    input_tokens = a.model_calls_per_run * a.input_tokens_per_call
    return input_tokens / 1e6 * in_price + a.output_tokens_per_run / 1e6 * out_price


def report(a: Assumptions) -> None:
    print("REQUEST VOLUME   avg RPS = DAU x requests/user/day / 86,400")
    print(f"{'scenario':22} {'avg RPS':>9} {'peak RPS':>9} {'peak DB/s':>10}")
    for s in SCENARIOS:
        avg = s.dau * a.requests_per_user_per_day / SECONDS_PER_DAY
        peak = avg * a.peak_factor
        print(f"{s.name:22} {avg:9.2f} {peak:9.2f} {peak * a.db_ops_per_request:10.0f}")

    print("\nAI WORK   concurrent = arrival rate x service time (Little's law)")
    header = f"{'scenario':22} {'runs/day':>10} {'peak/s':>8} {'conc':>7} {'calls/min':>10} {'avg TPM':>12} {'peak TPM':>12}"
    print(header)
    per_run_tokens = tokens_per_run(a)
    for s in SCENARIOS:
        runs_day = s.dau * a.runs_per_dau_per_day
        avg_runs = runs_day / SECONDS_PER_DAY
        peak_runs = avg_runs * a.peak_factor
        concurrent = peak_runs * a.service_seconds
        calls_min = peak_runs * a.model_calls_per_run * 60
        avg_tpm = avg_runs * per_run_tokens * 60
        peak_tpm = peak_runs * per_run_tokens * 60
        flag = ""
        if avg_tpm > META_TPM_LIMIT:
            flag = "  <-- OVER TPM AT AVERAGE LOAD"
        elif peak_tpm > META_TPM_LIMIT:
            flag = "  <-- over TPM at peak"
        print(
            f"{s.name:22} {runs_day:10,.0f} {peak_runs:8.2f} {concurrent:7.1f} "
            f"{calls_min:10,.0f} {avg_tpm:12,.0f} {peak_tpm:12,.0f}{flag}"
        )
    print(
        f"{'':22} {'':10} {'':8} {'':7} "
        f"{META_RPM_LIMIT:10,} {META_TPM_LIMIT:12,} {META_TPM_LIMIT:12,}   (verified limits)"
    )

    print(f"\nAI COST   per run ${cost_per_run(a):.4f} standard / "
          f"${cost_per_run(a, contributor=True):.4f} contributor")
    print(f"{'scenario':22} {'$/day':>10} {'$/month':>12} {'$/DAU/mo':>10} {'contrib $/mo':>13}")
    for s in SCENARIOS:
        runs_day = s.dau * a.runs_per_dau_per_day
        daily = runs_day * cost_per_run(a)
        monthly = daily * 30
        contrib = runs_day * cost_per_run(a, contributor=True) * 30
        per_dau = monthly / s.dau if s.dau else 0
        print(f"{s.name:22} {daily:10,.0f} {monthly:12,.0f} {per_dau:10.2f} {contrib:13,.0f}")

    print("\nMEDIA")
    print(f"{'scenario':22} {'stored TB':>10} {'$/mo':>9} {'egress TB/mo':>13} {'$/mo':>9} {'sam $/day':>10}")
    for s in SCENARIOS:
        stored_gb = s.registered * a.garments_per_user * a.mb_per_garment / 1024
        egress_gb_day = (
            s.dau * a.image_loads_per_dau_per_day * a.kb_per_image / 1024 / 1024
        )
        egress_gb_month = egress_gb_day * 30
        sam_day = s.dau * a.uploads_per_dau_per_day * SAM_PER_1000_IMAGES / 1000
        print(
            f"{s.name:22} {stored_gb / 1024:10.1f} {stored_gb * GCS_PER_GB_MONTH:9,.0f} "
            f"{egress_gb_month / 1024:13.1f} {egress_gb_month * CDN_PER_GB:9,.0f} {sam_day:10.0f}"
        )

    print(f"\nNote: muse-image-1.0 is limited to {META_IMAGE_RPM_LIMIT} RPM and needs its")
    print("own queue - it cannot share the stylist's concurrency budget.")
    print("\nAll non-provider figures are ASSUMPTIONS. None has been load-tested.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    defaults = Assumptions()
    for field_name, value in vars(defaults).items():
        parser.add_argument(
            f"--{field_name.replace('_', '-')}",
            type=float,
            default=value,
            help=f"default {value}",
        )
    args = parser.parse_args()
    report(Assumptions(**vars(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
