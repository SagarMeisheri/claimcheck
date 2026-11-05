"""Tests run with the same defaults whatever is in pipeline/.env: switches that change what a lookup does are fixed here,
before claimcheck.config reads them. A test for one of them passes it explicitly (Settings(research_sources=True))."""

import os

for name, value in {"CLAIMCHECK_RESEARCH_SOURCES": "0", "CLAIMCHECK_AUTO_SOURCES": "0", "CLAIMCHECK_AUTO_SOURCES_AS_FOUND": "0",
                    "CLAIMCHECK_PROFILE_CREATORS": "1", "CLAIMCHECK_OPINION_CHECK": "0"}.items():
    os.environ[name] = value
