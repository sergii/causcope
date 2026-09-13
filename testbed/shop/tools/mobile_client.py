from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("SHOP_BASE_URL", "http://app:8080")
INTERVAL_SECONDS = float(os.environ.get("INTERVAL_SECONDS", "2"))


def post_order(payload: dict[str, object], *, platform: str, version: str) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}/orders",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Client-Platform": platform,
            "X-App-Version": version,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def wait_for_app() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError("shop app did not become ready")


def main() -> int:
    wait_for_app()
    while True:
        web_status, _ = post_order(
            {"items": [{"product_id": 1, "quantity": 1}]},
            platform="web",
            version="2026.09",
        )
        mobile_status, _ = post_order(
            {"items": [{"product_id": 1, "quantity": "1"}]},
            platform="iOS",
            version="7.42.0",
        )
        print(
            f"scenario=mobile-bad-payload web_status={web_status} mobile_status={mobile_status}",
            flush=True,
        )
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
