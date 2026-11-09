"""Tests run with the same defaults whatever is in pipeline/.env: switches that change what a lookup does are fixed here,
before claimcheck.config reads them. A test for one of them passes it explicitly (Settings(research_sources=True))."""

import os

for name, value in {"CLAIMCHECK_RESEARCH_SOURCES": "0", "CLAIMCHECK_AUTO_SOURCES": "0", "CLAIMCHECK_AUTO_SOURCES_AS_FOUND": "0",
                    "CLAIMCHECK_PROFILE_CREATORS": "1", "CLAIMCHECK_OPINION_CHECK": "0", "CLAIMCHECK_BATCH_LOOKUPS": "0"}.items():
    os.environ[name] = value

# No test may reach a live service: with the keys blank (a variable already set is not overridden by .env) a call that slips through a
# stub fails at once instead of spending money or touching a stored verdict.
for name in ("GOOGLE_API_KEY", "PARALLEL_API_KEY", "YOUTUBE_API_KEY"):
    os.environ[name] = ""
