"""Cache the SYNTHETIC fixture company as a frozen snapshot, with no network access.

For demos and offline runs only. The company ("SYNTHETIC TEST CORP"), its CIK (9999999) and every number are
invented (see tests/synthetic.py). It goes through the real EdgarClient write path (hashing, sidecar metadata) via
a mock transport, so the rest of the workflow behaves exactly as with a live snapshot. The cached files carry a
SEC URL in their metadata because that is what the client records; the entity name is the marker that this is
fixture data. Replace it with `council human data fetch --cik <CIK>` once COUNCIL_SEC_USER_AGENT is set.

Usage: .venv/bin/python scripts/seed_synthetic_snapshot.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from council import config  # noqa: E402
from council.edgar.client import EdgarClient  # noqa: E402
from council.edgar.manifest import write_manifest  # noqa: E402
from tests import synthetic  # noqa: E402


def _transport(request: httpx.Request) -> httpx.Response:
    cik = synthetic.SYNTHETIC_CIK
    if request.url.path == f"/api/xbrl/companyfacts/CIK{cik}.json":
        return httpx.Response(200, json=synthetic.companyfacts())
    if request.url.path == f"/submissions/CIK{cik}.json":
        return httpx.Response(200, json=synthetic.submissions())
    return httpx.Response(404, text="not found")


def main() -> int:
    config.load_env()
    edgar_dir = config.edgar_dir()
    with EdgarClient(
        user_agent="Synthetic Fixture fixture@example.com",  # never sent anywhere: the transport is a mock
        cache_dir=edgar_dir,
        max_rps=10,
        transport=httpx.MockTransport(_transport),
        sleep=lambda _s: None,
    ) as client:
        client.get_company_facts(synthetic.SYNTHETIC_CIK)
        client.get_submissions(synthetic.SYNTHETIC_CIK)
    write_manifest(edgar_dir)
    print(f"cached {synthetic.ENTITY} (CIK {synthetic.SYNTHETIC_CIK}) under {edgar_dir}; no network request was made")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
