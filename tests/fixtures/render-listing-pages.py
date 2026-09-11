"""Render real Flask listing responses for the browser navigation regressions."""
import contextlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["UA_HOMES_PUBLIC_URL"] = "http://127.0.0.1:4173"

with contextlib.redirect_stdout(sys.stderr):
    from backend.test_trust_features import TrustFeatureTests

    fixture = TrustFeatureTests()
    fixture.setUp()
    pages = {}
    for listing_id in [fixture.target_id, fixture.realtor_listing_id]:
        response = fixture.client.get(f"/listing/{listing_id}")
        assert response.status_code == 200
        pages[listing_id] = {
            "html": response.get_data(as_text=True),
            "csp": response.headers["Content-Security-Policy"],
        }
    fixture.tearDownClass()

print(json.dumps(pages))
