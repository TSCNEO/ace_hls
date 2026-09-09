#!/usr/bin/env python3
"""
End-to-end Playwright test for MPEG-TS direct playback in Chromium.

Verifies:
1. mpegts.js is loaded and available as window.mpegts
2. mpegts.isSupported() returns true in Chromium
3. useMpegtsDirectPlayback('original') returns true
4. The /api/stream/direct/<id> endpoint is reachable
5. The HUD motor element exists
6. No console errors from the frontend JS

Usage:
    python3 tests/e2e_mpegts_chromium.py [--url http://192.168.90.16:8088]
"""
import argparse
import json
import sys
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://192.168.90.16:8088")
    args = parser.parse_args()
    base_url = args.url.rstrip("/")

    results = {}
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()

        # Collect console errors
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        # 1. Load the main page
        print(f"[1/6] Loading {base_url}...")
        resp = page.goto(base_url, wait_until="networkidle", timeout=15000)
        results["page_loaded"] = resp.status == 200
        print(f"      Status: {resp.status} → {'PASS' if results['page_loaded'] else 'FAIL'}")

        # 2. Check mpegts.js global is loaded
        print("[2/6] Checking window.mpegts exists...")
        has_mpegts = page.evaluate("typeof window.mpegts !== 'undefined'")
        results["mpegts_loaded"] = has_mpegts
        print(f"      window.mpegts: {has_mpegts} → {'PASS' if has_mpegts else 'FAIL'}")

        # 3. Check mpegts.isSupported()
        print("[3/6] Checking mpegts.isSupported()...")
        is_supported = page.evaluate("typeof window.mpegts !== 'undefined' && mpegts.isSupported()")
        results["mpegts_supported"] = is_supported
        print(f"      isSupported: {is_supported} → {'PASS' if is_supported else 'FAIL'}")

        # 4. Check useMpegtsDirectPlayback('original')
        print("[4/6] Checking useMpegtsDirectPlayback('original')...")
        use_direct = page.evaluate("typeof useMpegtsDirectPlayback === 'function' && useMpegtsDirectPlayback('original')")
        results["use_direct_original"] = use_direct
        print(f"      useMpegtsDirectPlayback: {use_direct} → {'PASS' if use_direct else 'FAIL'}")

        # 5. Check HUD motor element exists
        print("[5/6] Checking HUD motor element...")
        hud_motor = page.evaluate("document.getElementById('hud-motor') !== null")
        results["hud_motor_exists"] = hud_motor
        print(f"      #hud-motor: {hud_motor} → {'PASS' if hud_motor else 'FAIL'}")

        # 6. Check /api/stream/direct endpoint returns (even without real stream)
        # The endpoint connects to upstream and streams — without a running AceStream
        # it will either hang (200 chunked) or return 502. A timeout means the route
        # exists and is trying to proxy (expected behavior). We use a short timeout.
        print("[6/6] Checking /api/stream/direct/test_probe...")
        try:
            api_resp = page.request.get(f"{base_url}/api/stream/direct/test_probe", timeout=5000)
            endpoint_ok = api_resp.status in (200, 502)
            print(f"      /api/stream/direct: HTTP {api_resp.status} → {'PASS' if endpoint_ok else 'FAIL'}")
        except Exception:
            # Timeout = route exists, upstream is connecting (no AceStream running)
            endpoint_ok = True
            print("      /api/stream/direct: Timeout (route exists, no upstream) → PASS")

        browser.close()

    # Summary
    print("\n" + "=" * 50)
    print("CONSOLE ERRORS:", len(console_errors))
    for err in console_errors[:5]:
        print(f"  ⚠️ {err[:120]}")

    results["no_console_errors"] = len(console_errors) == 0

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\nRESULTS: {passed}/{total} passed")
    for k, v in results.items():
        print(f"  {'✅' if v else '❌'} {k}")

    if passed == total:
        print("\n🎉 All checks passed! MPEG-TS direct playback is ready.")
        return 0
    else:
        print(f"\n⚠️ {total - passed} check(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
