"""D2A browser parity: real Chromium against the Python-served production bundle.

TEST-ONLY. These tests never point at the repository's normal runtime stores, and
they never touch a product source file: isolation is environment/store
configuration plus monkeypatched *outbound* edges only (see ``fixture_data``).

Run explicitly, never as part of the normal unit gate:

    cd frontend && npm ci && npm run build && cd ..
    python3 -m pytest tests/browser -p no:cacheprovider

Screenshots land in ``var/d2a_screenshots`` (git-ignored, like every other
artifact under ``var/``).
"""
