# Testing Guide

This document explains how to run all tests for the MPP Video Generation API.

## Test Suite Overview

The project has three types of tests:

1. **Unit Tests** (`test_mpp.py`) - 77 tests
2. **Integration Tests** (`test_main.py`) - 35 tests
3. **End-to-End Tests** (`test-full-flow.py`) - 24 tests

**Total: 136 tests**

## Running Tests

### Run All Pytest Tests

```bash
# Run all pytest tests (unit + integration)
python -m pytest test_main.py test_mpp.py -v

# Run with coverage report
python -m pytest test_main.py test_mpp.py --cov=. --cov-report=term-missing

# Run specific test file
python -m pytest test_main.py -v
python -m pytest test_mpp.py -v

# Run specific test class
python -m pytest test_main.py::TestVideoGenerationWithPayment -v

# Run specific test
python -m pytest test_main.py::TestVideoGenerationWithPayment::test_generate_with_valid_payment_returns_200 -v
```

### Run End-to-End Tests

The E2E test script is designed to run standalone:

```bash
# Run all E2E tests
python test-full-flow.py

# Output shows detailed results for each test
```

**Note**: Do not run `test-full-flow.py` with pytest as it uses `asyncio.run()` internally which conflicts with pytest-asyncio.

## Test Coverage

### Unit Tests (test_mpp.py)

- Base64url encoding/decoding
- JCS encoding/decoding
- Challenge creation and verification
- Credential parsing and verification
- Transfer parameter verification
- Replay prevention
- Transaction signature verification
- Calldata decoding and verification
- Fee sponsorship
- Broadcast transaction
- Receipt generation
- Mock RPC client
- MPP configuration

### Integration Tests (test_main.py)

- Homepage endpoint
- Challenge generation (402 response)
- Payment verification
- Session management
- Replay prevention
- Credential validation
- Error handling
- Edge cases (duration boundaries, model validation)
- Pricing calculation
- Broadcast integration
- Receipt generation

### End-to-End Tests (test-full-flow.py)

1. Challenge Generation
2. Credential Creation and Verification
3. Full Payment Flow
4. Error Handling
5. Replay Prevention
6. Challenge Expiration
7. Dynamic Pricing Calculation
8. Session Cleanup
9. Receipt Generation
10. Multiple Video Models Support

## Test Results

Expected output:

```
test_main.py:  35 passed
test_mpp.py:   77 passed
test-full-flow.py: 24/24 passed
---------------------------------
TOTAL:         136/136 passed
```

## Continuous Integration

Add to your CI/CD pipeline:

```bash
# Install dependencies
pip install -r requirements.txt

# Run unit and integration tests
python -m pytest test_main.py test_mpp.py -v --tb=short

# Run E2E tests
python test-full-flow.py

# All tests must pass for deployment
```

## Debugging Tests

### Enable Verbose Output

```bash
# Pytest verbose mode
python -m pytest test_main.py -vv

# Show print statements
python -m pytest test_main.py -s
```

### Run Specific Test with Debug

```bash
# Run single test with full traceback
python -m pytest test_main.py::TestVideoGenerationWithPayment::test_generate_with_valid_payment_returns_200 -vvv --tb=long
```

### Test Individual Components

```bash
# Test challenge generation
python -c "
from mpp.challenge import create_challenge
from mpp.config import MPPConfig

config = MPPConfig(
    server_private_key='0x' + '01' * 32,
    mpp_secret_key='test-secret',
)

challenge = create_challenge(
    amount=0.50,
    recipient=config.SERVER_ADDRESS,
    realm='video-gen-api',
    method='tempo',
    secret_key=config.MPP_SECRET_KEY,
)

print('Challenge ID:', challenge['id'])
print('Test passed!')
"
```

## Troubleshooting

### Import Errors

```bash
# Ensure virtual environment is activated
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Reinstall dependencies
pip install -r requirements.txt
```

### Test Failures

1. Check environment variables are set correctly
2. Verify configuration in `.env` file
3. Run tests in isolation: `python -m pytest test_main.py -v`
4. Check logs for detailed error messages

### Async Test Issues

If you see asyncio errors:

```bash
# Ensure pytest-asyncio is installed
pip install pytest-asyncio

# Check pytest.ini configuration
cat pytest.ini
```

## Test Best Practices

1. **Run tests before committing**: Always run full test suite before pushing code
2. **Write tests for new features**: Add tests when adding new functionality
3. **Maintain coverage**: Keep test coverage above 90%
4. **Test edge cases**: Include boundary conditions and error scenarios
5. **Mock external services**: Use mocks for FAL API and RPC calls
6. **Keep tests fast**: Tests should complete in under 2 seconds each

## Performance

Expected test execution times:

- Unit tests: < 0.5 seconds
- Integration tests: < 1 second
- E2E tests: < 2 seconds
- **Total**: < 3 seconds

## Coverage Report

Generate coverage report:

```bash
# Install coverage tool
pip install pytest-cov

# Run with coverage
python -m pytest test_main.py test_mpp.py --cov=. --cov-report=html

# Open coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov\index.html  # Windows
```

Target: >90% code coverage

## Security Testing

Run security-focused tests:

```bash
# Test HMAC verification
python -m pytest test_mpp.py::TestChallengeCreation::test_create_challenge_hmac_binding -v

# Test replay prevention
python -m pytest test_mpp.py::TestReplayPrevention -v

# Test credential verification
python -m pytest test_mpp.py::TestCredentialVerification -v
```

## Next Steps

After tests pass:

1. ✅ Review code coverage
2. ✅ Check for security vulnerabilities
3. ✅ Verify error handling
4. ✅ Test with real FAL API key (optional)
5. ✅ Deploy to staging environment
6. ✅ Run integration tests in staging
7. ✅ Deploy to production

---

For more information, see:
- `docs/mpp-integration-guide.md` - Integration documentation
- `docs/mpp-curl-examples.md` - API examples
- `PHASE6_7_COMPLETE.md` - Implementation summary
