# Tests

## Running tests

```bash
# From the repo root:

# Run all tests
pytest tests/ -v

# Run specific test files
pytest tests/test_main.py -v       # API route tests
pytest tests/test_mpp.py -v        # MPP module tests (challenge, credential, broadcast)
pytest tests/test_client_pay.py -v # Client payment script tests

# Run with output
pytest tests/ -v -s
```

## Test files

| File | What it covers |
|------|---------------|
| `test_main.py` | API endpoints, request validation, payment flow integration |
| `test_mpp.py` | Challenge creation/verification, credential parsing, fee sponsorship, RPC client |
| `test_client_pay.py` | Client-side transaction signing, credential construction, CLI argument handling |
| `test-full-flow.py` | End-to-end flow test (standalone, run with `python tests/test-full-flow.py`) |
| `test-tempo-setup.py` | Tempo blockchain connectivity checks (standalone) |
| `test-manual.sh` | Shell-based manual test script |

## Configuration

Tests use `pytest` with async support via `pytest-asyncio`. See `pytest.ini` in this directory for settings.

Tests mock external dependencies (FAL AI, blockchain RPC) so no network access or real keys are needed to run the suite.
