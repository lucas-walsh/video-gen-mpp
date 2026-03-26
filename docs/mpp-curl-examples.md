# MPP Challenge Generation - cURL and Python Client Examples

This document demonstrates how to interact with the Video Generation API's MPP (Machine Payments Protocol) challenge generation endpoint.

## Overview

When you request video generation without payment credentials, the API returns a `402 Payment Required` response with:
- A `WWW-Authenticate: Payment` header containing the challenge
- A response body in Problem Details format (RFC 9457)
- Dynamic pricing based on FAL API costs + 20% markup

## Example: Request Video Generation Challenge

### cURL Command

```bash
curl -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A beautiful sunset over mountains",
    "duration_seconds": 5,
    "model": "fal-ai/veo3.1/fast"
  }'
```

### Example Response

**HTTP Status:** `402 Payment Required`

**Response Headers:**
```
HTTP/1.1 402 Payment Required
Content-Type: application/json
Cache-Control: no-store
WWW-Authenticate: Payment realm="video-gen-api", id="a1b2c3d4...", method="tempo", intent="charge", request="eyJhbW91bnQiOiIwLjMwMDAwMCIsImN1cnJlbmN5IjoicGF0aFVTRCIsImN1cnJlbmN5X2FkZHJlc3MiOiIweDIwYzAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAiLCJtZXRob2QiOiJ0ZW1wbyIsInJlY2lwaWVudCI6IjB4YWJjZC4uLiIsInJlYWxtIjoidmlkZW8tZ2VuLWFwaSIsInRpbWVzdGFtcCI6IjIwMjQtMDEtMDFUMDA6MDA6MDBaIn0", expires="2024-01-01T00:05:00+00:00"
```

**Response Body:**
```json
{
  "type": "https://paymentauth.org/problems/payment-required",
  "title": "Payment Required",
  "status": 402,
  "detail": "This resource requires payment of $0.30 USD in pathUSD",
  "amount": "300000",
  "currency": "0x20c0000000000000000000000000000000000000",
  "expires_in": 300
}
```

## Challenge Header Fields

The `WWW-Authenticate: Payment` header contains the following parameters:

| Field | Description | Example |
|-------|-------------|---------|
| `realm` | API realm identifier | `"video-gen-api"` |
| `id` | Unique challenge ID (HMAC-based) | `"a1b2c3d4e5f6..."` |
| `method` | Payment method | `"tempo"` |
| `intent` | Payment intent type | `"charge"` |
| `request` | Base64url-encoded challenge request (JCS format) | `"eyJhbW91bnQi..."` |
| `expires` | Challenge expiration timestamp (ISO 8601) | `"2024-01-01T00:05:00+00:00"` |

## Response Body Fields

| Field | Description | Example |
|-------|-------------|---------|
| `type` | Problem type URI | `"https://paymentauth.org/problems/payment-required"` |
| `title` | Human-readable title | `"Payment Required"` |
| `status` | HTTP status code | `402` |
| `detail` | Description with amount | `"This resource requires payment of $0.30 USD in pathUSD"` |
| `amount` | Amount in currency smallest units (micro USD) | `"300000"` |
| `currency` | Token contract address | `"0x20c0000000000000000000000000000000000000"` |
| `expires_in` | Seconds until challenge expires | `300` |

## Pricing Calculation

The challenge amount is calculated as:

```
FAL API Price × Duration × (1 + Markup %)
```

Default markup: **20%**

### Example Calculations

| Model | Price/sec | Duration | Subtotal | Final (with 20% markup) |
|-------|-----------|----------|----------|------------------------|
| fal-ai/veo3.1/fast | $0.05 | 5s | $0.25 | $0.30 |
| fal-ai/veo3.1/fast | $0.05 | 10s | $0.50 | $0.60 |
| fal-ai/veo3.1 | $0.08 | 5s | $0.40 | $0.48 |
| fal-ai/kling/video/v2.5/pro | $0.10 | 5s | $0.50 | $0.60 |

## Supported Video Models

- `fal-ai/veo3.1/fast` (default)
- `fal-ai/veo3.1`
- `fal-ai/kling/video/v2.5/pro`
- `fal-ai/wan/v2.2-a14b/image-to-video`

## Challenge Expiration

- Challenges expire in **5 minutes** (300 seconds) by default
- Use the `expires` field in the header or `expires_in` in the body to check validity
- Expired challenges will be rejected during payment verification

## Next Steps

After receiving the challenge:

1. Decode the `request` field from the challenge header
2. Create a payment credential with the required amount
3. Submit the credential in the `Authorization: Payment` header
4. Include the `X-Session-ID` from the challenge response

See the MPP specification for credential creation and payment flow details.

## Python Client Usage

A Python client script is provided to automate the entire payment flow:

### Setup

```bash
# Install dependencies
pip install eth-account httpx python-dotenv

# Set your client private key
export CLIENT_PRIVATE_KEY="0xabc123..."
```

### Basic Usage

```bash
python client-pay.py \
  --prompt "A cat playing piano" \
  --duration 5 \
  --url http://localhost:8000
```

### Command-Line Options

```
usage: client-pay.py [-h] --prompt PROMPT [--duration DURATION] [--url URL]
                     [--model MODEL] [--private-key PRIVATE_KEY] [-v]

options:
  -h, --help            show this help message and exit
  --prompt PROMPT       Video generation prompt (required)
  --duration DURATION   Video duration in seconds (default: 5)
  --url URL             API base URL (default: http://localhost:8000)
  --model MODEL         Video model (default: fal-ai/veo3.1/fast)
  --private-key PRIVATE_KEY
                        Client private key (or set CLIENT_PRIVATE_KEY env var)
  -v, --verbose         Enable verbose output
```

### Examples

```bash
# Basic usage with environment variable
export CLIENT_PRIVATE_KEY="0xabc123..."
python client-pay.py --prompt "A beautiful sunset over mountains"

# Specify duration and model
python client-pay.py \
  --prompt "A robot walking through a forest" \
  --duration 10 \
  --model "fal-ai/veo3.1"

# Use custom API URL
python client-pay.py \
  --prompt "Ocean waves" \
  --url "https://api.example.com"

# Verbose output for debugging
python client-pay.py \
  --prompt "Test video" \
  --verbose

# Provide private key directly (not recommended for production)
python client-pay.py \
  --prompt "Test" \
  --private-key "0xabc123..."
```

### Expected Output

```
============================================================
MPP Client Payment Flow
============================================================

Step 1: Requesting video generation...
  API URL: http://localhost:8000
  Model: fal-ai/veo3.1/fast
  Duration: 5s
  Prompt: A cat playing piano

Step 2: Got 402 challenge
  Challenge ID: abc123def456...
  Amount: $0.60 pathUSD
  Recipient: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
  Expires: 2025-01-15T12:05:00Z

Step 3: Creating TIP-20 transfer transaction...
  To: 0x20c0000000000000000000000000000000000000
  From: 0x5B38Da6a701c568545dCfcB03FcB875f56beddC4
  Amount: 600000 (micro USD)
  Nonce: 0
  Type: 0x76

Step 4: Signing transaction locally...
  Domain: 0x76 (user signature)
  Note: Transaction signed but NOT broadcast
  Signature: 0x1a2b3c4d5e6f7890...
  Transaction Hash: 0xabc123...

Step 5: Creating payment credential...
  Credential encoded: eyJjaGFsbGVuZ2UiOnsiaWQiOiJhYmMxMjMiLCJyZ...

Step 6: Sending credential to server...

Step 7: Got response: 200 OK
  Job ID: job_abc123def456
  Status: processing
  Cost: $0.60

============================================================
Payment flow completed successfully!
============================================================
```

### Programmatic Usage

```python
from client_pay import run_payment_flow

result = run_payment_flow(
    api_url="http://localhost:8000",
    prompt="A cat playing piano",
    duration=5,
    private_key="0xabc123...",
    model="fal-ai/veo3.1/fast",
    verbose=True,
)

if result["success"]:
    print(f"Job ID: {result['job_id']}")
    print(f"Status: {result['status']}")
    print(f"Transaction Hash: {result['transaction_hash']}")
else:
    print(f"Error: {result['error']}")
```

## Python Client Usage

A Python client script is provided to automate the entire payment flow:

### Setup

```bash
# Install dependencies
pip install eth-account httpx python-dotenv

# Set your client private key
export CLIENT_PRIVATE_KEY="0xabc123..."
```

### Basic Usage

```bash
python client-pay.py \
  --prompt "A cat playing piano" \
  --duration 5 \
  --url http://localhost:8000
```

### Command-Line Options

```
usage: client-pay.py [-h] --prompt PROMPT [--duration DURATION] [--url URL]
                     [--model MODEL] [--private-key PRIVATE_KEY] [-v]

options:
  -h, --help            show this help message and exit
  --prompt PROMPT       Video generation prompt (required)
  --duration DURATION   Video duration in seconds (default: 5)
  --url URL             API base URL (default: http://localhost:8000)
  --model MODEL         Video model (default: fal-ai/veo3.1/fast)
  --private-key PRIVATE_KEY
                        Client private key (or set CLIENT_PRIVATE_KEY env var)
  -v, --verbose         Enable verbose output
```

### Examples

```bash
# Basic usage with environment variable
export CLIENT_PRIVATE_KEY="0xabc123..."
python client-pay.py --prompt "A beautiful sunset over mountains"

# Specify duration and model
python client-pay.py \
  --prompt "A robot walking through a forest" \
  --duration 10 \
  --model "fal-ai/veo3.1"

# Use custom API URL
python client-pay.py \
  --prompt "Ocean waves" \
  --url "https://api.example.com"

# Verbose output for debugging
python client-pay.py \
  --prompt "Test video" \
  --verbose

# Provide private key directly (not recommended for production)
python client-pay.py \
  --prompt "Test" \
  --private-key "0xabc123..."
```

### Expected Output

```
============================================================
MPP Client Payment Flow
============================================================

Step 1: Requesting video generation...
  API URL: http://localhost:8000
  Model: fal-ai/veo3.1/fast
  Duration: 5s
  Prompt: A cat playing piano

Step 2: Got 402 challenge
  Challenge ID: abc123def456...
  Amount: $0.60 pathUSD
  Recipient: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
  Expires: 2025-01-15T12:05:00Z

Step 3: Creating TIP-20 transfer transaction...
  To: 0x20c0000000000000000000000000000000000000
  From: 0x5B38Da6a701c568545dCfcB03FcB875f56beddC4
  Amount: 600000 (micro USD)
  Nonce: 0
  Type: 0x76

Step 4: Signing transaction locally...
  Domain: 0x76 (user signature)
  Note: Transaction signed but NOT broadcast
  Signature: 0x1a2b3c4d5e6f7890...
  Transaction Hash: 0xabc123...

Step 5: Creating payment credential...
  Credential encoded: eyJjaGFsbGVuZ2UiOnsiaWQiOiJhYmMxMjMiLCJyZ...

Step 6: Sending credential to server...

Step 7: Got response: 200 OK
  Job ID: job_abc123def456
  Status: processing
  Cost: $0.60

============================================================
Payment flow completed successfully!
============================================================
```

### Programmatic Usage

```python
from client_pay import run_payment_flow

result = run_payment_flow(
    api_url="http://localhost:8000",
    prompt="A cat playing piano",
    duration=5,
    private_key="0xabc123...",
    model="fal-ai/veo3.1/fast",
    verbose=True,
)

if result["success"]:
    print(f"Job ID: {result['job_id']}")
    print(f"Status: {result['status']}")
    print(f"Transaction Hash: {result['transaction_hash']}")
else:
    print(f"Error: {result['error']}")
```

## Troubleshooting

### Common Issues

**1. "CLIENT_PRIVATE_KEY environment variable not set"**

```bash
export CLIENT_PRIVATE_KEY="0xabc123..."
```

**2. "Failed to decode challenge request"**

Ensure the server is running and returning valid WWW-Authenticate headers.

**3. "Unauthorized" or "Payment failed"**

- Check that your private key is valid
- Verify the transaction is signed with domain 0x76
- Ensure the challenge hasn't expired (5 minute TTL)

**4. "Service unavailable"**

The server may be unable to fetch pricing from Fal.ai. Check:
- FAL_AI_KEY is set correctly on the server
- Network connectivity to Fal.ai

### Debug Mode

Use verbose mode to see detailed transaction information:

```bash
python client-pay.py --prompt "Test" --verbose
```

## Error Responses

### Pricing API Unavailable (503)

```json
{
  "success": false,
  "error": "Unable to fetch pricing from Fal.ai",
  "details": {
    "endpoint_id": "fal-ai/veo3.1/fast",
    "possible_causes": [
      "Invalid or missing FAL_AI_KEY",
      "Fal.ai API is temporarily unavailable",
      "Network connectivity issue"
    ]
  }
}
```

### Invalid Request (400)

```json
{
  "success": false,
  "error": "duration_seconds must be between 1 and 30"
}
```

## Logging

The server logs challenge generation events:

```
INFO: Challenge generated: amount=0.300000 USD, recipient=0xabcd..., expires_in=300s, session_id=quote_abc123
```

Note: Sensitive data (HMAC keys, private keys) are never logged.

## Full Payment Flow Example

### Complete cURL Flow

This example shows the complete payment flow from challenge to video generation.

#### Step 1: Request Challenge

```bash
# Get challenge from server
CHALLENGE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cat playing piano",
    "duration_seconds": 5,
    "model": "fal-ai/veo3.1/fast"
  }')

# Extract response body and status code
RESPONSE_BODY=$(echo "$CHALLENGE_RESPONSE" | sed '$d')
HTTP_CODE=$(echo "$CHALLENGE_RESPONSE" | tail -n1)

echo "HTTP Status: $HTTP_CODE"
echo "Response: $RESPONSE_BODY"

# Extract session_id
SESSION_ID=$(echo "$RESPONSE_BODY" | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")
echo "Session ID: $SESSION_ID"

# Extract WWW-Authenticate header
WWW_AUTH=$(curl -s -D - -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cat playing piano",
    "duration_seconds": 5
  }' | grep -i "www-authenticate" | cut -d' ' -f2-)

echo "Challenge: $WWW_AUTH"
```

#### Step 2: Create Payment Credential

Use the Python client to create and submit the credential:

```bash
export CLIENT_PRIVATE_KEY="0x..."
python client-pay.py --prompt "A cat playing piano" --duration 5 --url http://localhost:8000
```

#### Step 3: Check Job Status

```bash
JOB_ID="job_abc123"  # From payment response
curl http://localhost:8000/api/video/jobs/$JOB_ID
```

### Error Handling Examples

#### Handling 402 Payment Required

```bash
RESPONSE=$(curl -s -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test", "duration_seconds": 5}')

STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))")

if [ "$STATUS" = "402" ]; then
    echo "Payment required"
    # Extract challenge and create credential
    SESSION_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")
    # ... proceed with payment
fi
```

#### Handling 503 Service Unavailable

```bash
RESPONSE=$(curl -s -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test", "duration_seconds": 5}')

STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))")

if [ "$STATUS" = "503" ]; then
    echo "Service unavailable - FAL API error"
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['error'])")
    echo "Error: $ERROR"
    # Retry later or notify user
fi
```

#### Handling 400 Bad Request

```bash
RESPONSE=$(curl -s -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "", "duration_seconds": 5}')

if echo "$RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); exit(0 if 'error' in d else 1)"; then
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['error'])")
    echo "Validation error: $ERROR"
    # Fix request and retry
fi
```

## Testing

### Run Full Test Suite

```bash
# Run comprehensive test suite
python test-full-flow.py

# Run pytest test suite
pytest test_main.py -v
pytest test_mpp.py -v
```

### Test Specific Scenarios

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
    currency='pathUSD',
    currency_address=config.PATHUSD_ADDRESS,
    expires_in=300,
    secret_key=config.MPP_SECRET_KEY,
)

print('Challenge created:', challenge['id'])
"

# Test credential verification
python -c "
from mpp.credential import verify_credential, create_credential
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

credential_b64 = create_credential(
    challenge=challenge,
    transaction_hash='0x' + 'ab' * 32,
    transfer_params={'recipient': config.SERVER_ADDRESS, 'amount': '0.50', 'currency': 'pathUSD'},
)

is_valid, cred, error = verify_credential(
    auth_header=f'Payment {credential_b64}',
    secret_key=config.MPP_SECRET_KEY,
    expected_realm='video-gen-api',
)

print('Valid:', is_valid, 'Error:', error)
"
```

## Monitoring

### Check Revenue Tracking

```bash
# View server logs for revenue
tail -f logs/server.log | grep "Revenue tracked"

# Check payment statistics
tail -f logs/server.log | grep -E "(Payment|FAL API)" | tail -20
```

### Debug Payment Issues

```bash
# Enable verbose logging
export LOG_LEVEL=DEBUG
python main.py

# Check for specific errors
grep "ERROR" logs/server.log | tail -20
grep "Payment verification failed" logs/server.log
grep "FAL API call failed" logs/server.log
```

## Best Practices

1. **Always use HTTPS in production**
2. **Store private keys securely** (environment variables, vault)
3. **Implement retry logic** for transient failures
4. **Monitor revenue and error rates**
5. **Rotate HMAC keys periodically**
6. **Implement proper session management**
7. **Handle all error cases gracefully**
8. **Log all payment attempts for auditing**

## Support

For issues:

1. Check server logs
2. Run test suite
3. Verify configuration
4. Check FAL API status
5. Review MPP specification

See `docs/mpp-integration-guide.md` for comprehensive integration documentation.

## Full Payment Flow Example

### Complete cURL Flow

This example shows the complete payment flow from challenge to video generation.

#### Step 1: Request Challenge

```bash
# Get challenge from server
CHALLENGE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cat playing piano",
    "duration_seconds": 5,
    "model": "fal-ai/veo3.1/fast"
  }')

# Extract response body and status code
RESPONSE_BODY=$(echo "$CHALLENGE_RESPONSE" | sed '$d')
HTTP_CODE=$(echo "$CHALLENGE_RESPONSE" | tail -n1)

echo "HTTP Status: $HTTP_CODE"
echo "Response: $RESPONSE_BODY"

# Extract session_id
SESSION_ID=$(echo "$RESPONSE_BODY" | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")
echo "Session ID: $SESSION_ID"

# Extract WWW-Authenticate header
WWW_AUTH=$(curl -s -D - -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cat playing piano",
    "duration_seconds": 5
  }' | grep -i "www-authenticate" | cut -d' ' -f2-)

echo "Challenge: $WWW_AUTH"
```

#### Step 2: Create Payment Credential

Use the Python client to create and submit the credential:

```bash
export CLIENT_PRIVATE_KEY="0x..."
python client-pay.py --prompt "A cat playing piano" --duration 5 --url http://localhost:8000
```

#### Step 3: Check Job Status

```bash
JOB_ID="job_abc123"  # From payment response
curl http://localhost:8000/api/video/jobs/$JOB_ID
```

### Error Handling Examples

#### Handling 402 Payment Required

```bash
RESPONSE=$(curl -s -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test", "duration_seconds": 5}')

STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))")

if [ "$STATUS" = "402" ]; then
    echo "Payment required"
    # Extract challenge and create credential
    SESSION_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")
    # ... proceed with payment
fi
```

#### Handling 503 Service Unavailable

```bash
RESPONSE=$(curl -s -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test", "duration_seconds": 5}')

STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))")

if [ "$STATUS" = "503" ]; then
    echo "Service unavailable - FAL API error"
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['error'])")
    echo "Error: $ERROR"
    # Retry later or notify user
fi
```

#### Handling 400 Bad Request

```bash
RESPONSE=$(curl -s -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "", "duration_seconds": 5}')

if echo "$RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); exit(0 if 'error' in d else 1)"; then
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['error'])")
    echo "Validation error: $ERROR"
    # Fix request and retry
fi
```

## Testing

### Run Full Test Suite

```bash
# Run comprehensive test suite
python test-full-flow.py

# Run pytest test suite
pytest test_main.py -v
pytest test_mpp.py -v
```

### Test Specific Scenarios

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
    currency='pathUSD',
    currency_address=config.PATHUSD_ADDRESS,
    expires_in=300,
    secret_key=config.MPP_SECRET_KEY,
)

print('Challenge created:', challenge['id'])
"

# Test credential verification
python -c "
from mpp.credential import verify_credential, create_credential
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

credential_b64 = create_credential(
    challenge=challenge,
    transaction_hash='0x' + 'ab' * 32,
    transfer_params={'recipient': config.SERVER_ADDRESS, 'amount': '0.50', 'currency': 'pathUSD'},
)

is_valid, cred, error = verify_credential(
    auth_header=f'Payment {credential_b64}',
    secret_key=config.MPP_SECRET_KEY,
    expected_realm='video-gen-api',
)

print('Valid:', is_valid, 'Error:', error)
"
```

## Monitoring

### Check Revenue Tracking

```bash
# View server logs for revenue
tail -f logs/server.log | grep "Revenue tracked"

# Check payment statistics
tail -f logs/server.log | grep -E "(Payment|FAL API)" | tail -20
```

### Debug Payment Issues

```bash
# Enable verbose logging
export LOG_LEVEL=DEBUG
python main.py

# Check for specific errors
grep "ERROR" logs/server.log | tail -20
grep "Payment verification failed" logs/server.log
grep "FAL API call failed" logs/server.log
```

## Best Practices

1. **Always use HTTPS in production**
2. **Store private keys securely** (environment variables, vault)
3. **Implement retry logic** for transient failures
4. **Monitor revenue and error rates**
5. **Rotate HMAC keys periodically**
6. **Implement proper session management**
7. **Handle all error cases gracefully**
8. **Log all payment attempts for auditing**

## Support

For issues:

1. Check server logs
2. Run test suite
3. Verify configuration
4. Check FAL API status
5. Review MPP specification

See `docs/mpp-integration-guide.md` for comprehensive integration documentation.
