# MPP Integration Guide

This guide provides comprehensive documentation for integrating the Machine Payments Protocol (MPP) with the Video Generation API.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Configuration](#configuration)
4. [API Reference](#api-reference)
5. [Payment Flow](#payment-flow)
6. [Error Handling](#error-handling)
7. [Security Considerations](#security-considerations)
8. [Monitoring & Logging](#monitoring--logging)
9. [Troubleshooting](#troubleshooting)

## Overview

The Video Generation API uses MPP (Machine Payments Protocol) on Tempo Network for micropayments. This enables:

- **Pay-per-use pricing**: Users pay only for what they use
- **Dynamic pricing**: Prices adjust based on FAL API costs + markup
- **Trustless payments**: Cryptographic verification ensures payment integrity
- **Fee sponsorship**: Server pays gas fees, users only pay for the service

### Key Features

- **20% markup** on FAL API costs
- **5-minute challenge expiration** for security
- **Replay prevention** using credential tracking
- **Multiple video models** with different pricing tiers
- **Graceful error handling** for payment and FAL API failures

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Client    │──────│  Video API   │──────│  FAL API    │
│             │      │   (MPP)      │      │             │
└─────────────┘      └──────────────┘      └─────────────┘
       │                     │
       │                     │
       ▼                     ▼
┌─────────────┐      ┌──────────────┐
│  Tempo RPC  │      │  Revenue     │
│  (Mocked)   │      │  Tracking    │
└─────────────┘      └──────────────┘
```

### Components

1. **Client**: Initiates video generation requests
2. **Video API**: Handles MPP payment verification and FAL integration
3. **FAL API**: Generates videos based on prompts
4. **Tempo RPC**: Blockchain RPC for transaction verification (mocked in testnet)

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# FAL AI Configuration
FAL_AI_KEY=your_fal_ai_api_key

# MPP Configuration
SERVER_PRIVATE_KEY=0x...your_server_private_key
MPP_SECRET_KEY=your_secret_key_for_hmac
TEMPO_RPC_URL=https://rpc.testnet.tempo.xyz
PATHUSD_ADDRESS=0x20c0000000000000000000000000000000000000
TEMPO_CHAIN_ID=57059

# Server Configuration
HOST=0.0.0.0
PORT=8000
```

### Configuration Options

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `FAL_AI_KEY` | FAL AI API key for video generation | - | Yes |
| `SERVER_PRIVATE_KEY` | Server's private key for fee sponsorship | - | Yes |
| `MPP_SECRET_KEY` | Secret key for HMAC challenge binding | - | Yes |
| `TEMPO_RPC_URL` | Tempo Network RPC endpoint | `https://rpc.testnet.tempo.xyz` | No |
| `PATHUSD_ADDRESS` | pathUSD token contract address | `0x20c0...0000` | No |
| `TEMPO_CHAIN_ID` | Chain ID for Tempo Network | `57059` | No |
| `HOST` | Server bind address | `0.0.0.0` | No |
| `PORT` | Server port | `8000` | No |

### Pricing Configuration

Pricing is configured in `config.py`:

```python
MARKUP_PERCENT = 20  # 20% markup on FAL costs
QUOTE_TTL_SECONDS = 300  # 5 minutes

SUPPORTED_VIDEO_MODELS = [
    "fal-ai/veo3.1/fast",
    "fal-ai/veo3.1",
    "fal-ai/kling/video/v2.5/pro",
    "fal-ai/wan/v2.2-a14b/image-to-video",
]

DEFAULT_VIDEO_MODEL = "fal-ai/veo3.1/fast"
```

## API Reference

### POST /api/video/generate

Generate a video with the specified prompt and duration.

#### Request Headers

- `Content-Type: application/json`
- `Authorization: Payment <credential>` (optional, for payment)
- `X-Session-ID: <session_id>` (required with Authorization)

#### Request Body

```json
{
  "prompt": "A cat playing piano",
  "duration_seconds": 5,
  "model": "fal-ai/veo3.1/fast"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | Yes | Video generation prompt |
| `duration_seconds` | integer | Yes | Duration in seconds (1-30) |
| `model` | string | No | Video model (default: `fal-ai/veo3.1/fast`) |

#### Response: 402 Payment Required (No Payment Credential)

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

**Headers:**
- `WWW-Authenticate: Payment realm="video-gen-api", id="...", method="tempo", ...`
- `Cache-Control: no-store`

#### Response: 200 OK (Payment Verified)

```json
{
  "success": true,
  "job_id": "job_abc123",
  "status": "processing",
  "cost_usd": 0.30,
  "message": "Payment verified. Video generation started."
}
```

**Headers:**
- `Payment-Receipt: <base64url_encoded_receipt>`

#### Response: 400 Bad Request

```json
{
  "success": false,
  "error": "duration_seconds must be between 1 and 30"
}
```

#### Response: 401 Unauthorized

```json
{
  "success": false,
  "error": "Challenge HMAC binding verification failed"
}
```

#### Response: 402 Payment Required (Payment Failed)

```json
{
  "success": false,
  "error": "Transaction verification failed: Recipient mismatch"
}
```

#### Response: 503 Service Unavailable

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

### GET /api/video/jobs/{job_id}

Check the status of a video generation job.

#### Response: 200 OK

```json
{
  "job_id": "job_abc123",
  "status": "completed",
  "video_url": "https://...",
  "width": 1920,
  "height": 1080,
  "created_at": "2025-01-15T12:00:00Z"
}
```

**Status Values:**
- `queued`: Job is in queue
- `processing`: Job is being processed
- `completed`: Job completed successfully
- `failed`: Job failed

### GET /api/video/gallery

Get list of generated videos (currently returns empty list).

## Payment Flow

### Step-by-Step Flow

1. **Client Request**: Client sends video generation request without payment
2. **Challenge Generation**: Server returns 402 with payment challenge
3. **Credential Creation**: Client creates payment credential with transaction
4. **Credential Submission**: Client resubmits request with credential
5. **Verification**: Server verifies credential (HMAC, signature, calldata)
6. **Broadcast**: Server sponsors fee and broadcasts transaction
7. **FAL Integration**: Server calls FAL API to generate video
8. **Receipt**: Server returns payment receipt and job ID

### Challenge Structure

```python
{
    "id": "<hmac_hex>",
    "realm": "video-gen-api",
    "method": "tempo",
    "intent": "charge",
    "request": "<base64url_encoded_jcs>",
    "expires": "<iso8601_timestamp>"
}
```

### Request Parameters (Decoded)

```python
{
    "amount": "0.300000",
    "currency": "pathUSD",
    "currency_address": "0x20c0...",
    "method": "tempo",
    "recipient": "0x...",
    "realm": "video-gen-api",
    "timestamp": "2025-01-15T12:00:00Z"
}
```

### Credential Structure

```python
{
    "challenge": { ... },  # Echoed challenge
    "type": "transaction",
    "payload": {
        "transaction_hash": "0x...",
        "transaction_bytes": "0x...",
        "transfer": {
            "recipient": "0x...",
            "amount": "0.30",
            "currency": "pathUSD"
        }
    }
}
```

## Error Handling

### Payment Errors

| Error | Code | Description | Action |
|-------|------|-------------|--------|
| Invalid credential format | 402 | Credential parsing failed | Re-create credential |
| Invalid or expired payment credential | 401 | Session expired or invalid | Get new challenge |
| Challenge HMAC binding verification failed | 401 | Tampered challenge | Use server-provided challenge |
| Transaction verification failed | 402 | Wrong recipient/amount | Fix transaction parameters |
| Signature verification failed | 402 | Invalid signature | Re-sign transaction |
| Credential already used | 401 | Replay attempt | Create new credential |

### FAL API Errors

| Error | Code | Description | Action |
|-------|------|-------------|--------|
| Unable to fetch pricing | 503 | FAL API unavailable | Retry later |
| Failed to submit video generation request | 503 | FAL submission failed | Retry or refund |

### Broadcast Errors

| Error | Code | Description | Action |
|-------|------|-------------|--------|
| Fee sponsorship failed | 402 | Cannot sponsor transaction | Check server key |
| Transaction broadcast failed | 503 | RPC failure | Retry broadcast |

### Error Logging

All errors are logged with appropriate severity:

- **INFO**: Successful operations, revenue tracking
- **WARNING**: Payment verification failures, validation errors
- **ERROR**: FAL API failures, broadcast failures, system errors

## Security Considerations

### HMAC Binding

Challenges are bound to the server using HMAC-SHA256:

```python
hmac_input = f"{request_b64}.{secret_key}".encode('utf-8')
challenge_id = hmac.new(
    secret_key.encode('utf-8'),
    request_jcs.encode('utf-8'),
    hashlib.sha256
).hexdigest()
```

**Best Practices:**
- Never expose `MPP_SECRET_KEY`
- Use cryptographically secure random keys
- Rotate keys periodically

### Replay Prevention

Credentials are tracked to prevent reuse:

```python
used_credentials.add(challenge_id)
```

**Best Practices:**
- Persist `used_credentials` across server restarts
- Implement cleanup for old credentials
- Monitor for replay attempts

### Input Validation

All inputs are validated:

- Duration: 1-30 seconds
- Prompt: Non-empty string
- Model: Must be in supported list
- Amount: Must match challenge exactly

### Private Key Handling

**Critical:**
- Never log private keys
- Store in environment variables or secure vault
- Use separate keys for testnet/mainnet
- Rotate keys if compromised

## Monitoring & Logging

### Revenue Tracking

The system tracks revenue in memory:

```python
revenue_tracker = {
    "total_pathusd_received": 0.0,
    "successful_payments": 0,
    "failed_payments": 0,
    "failed_fal_calls": 0,
}
```

### Log Messages

**Successful Payment:**
```
INFO - Revenue tracked: $0.300000 USD | Total: $15.600000
INFO - FAL API call successful: model=fal-ai/veo3.1/fast, status=submitted
INFO - Transaction broadcast successful: 0xabc123...
```

**Payment Failure:**
```
WARNING - Payment verification failed: Challenge HMAC binding verification failed
WARNING - Transfer parameter verification failed: Amount insufficient
```

**FAL Failure:**
```
ERROR - FAL API call failed: model=fal-ai/veo3.1/fast, status=failed, error=HTTP 401
ERROR - Failed to submit to Fal.ai: HTTP 401 - Unauthorized
```

### Metrics to Monitor

1. **Revenue**: `total_pathusd_received`
2. **Success Rate**: `successful_payments / (successful_payments + failed_payments)`
3. **FAL Reliability**: `failed_fal_calls`
4. **Challenge Expiration**: Monitor session cleanup frequency
5. **Replay Attempts**: Log frequency of replay prevention triggers

## Troubleshooting

### Common Issues

#### 1. "Unable to fetch pricing from Fal.ai"

**Causes:**
- Missing or invalid `FAL_AI_KEY`
- Network connectivity issues
- FAL API downtime

**Solutions:**
```bash
# Verify FAL key is set
echo $FAL_AI_KEY

# Test FAL API connectivity
curl -H "Authorization: Key $FAL_AI_KEY" \
  https://api.fal.ai/v1/models/pricing?endpoint_id=fal-ai/veo3.1/fast

# Check server logs for details
tail -f logs/server.log | grep "Fal.ai"
```

#### 2. "Challenge HMAC binding verification failed"

**Causes:**
- Tampered challenge
- Mismatched `MPP_SECRET_KEY`
- Expired challenge

**Solutions:**
- Use challenge directly from server response
- Verify `MPP_SECRET_KEY` matches server configuration
- Complete payment within 5 minutes

#### 3. "Transaction verification failed: Recipient mismatch"

**Causes:**
- Wrong recipient address in transaction
- Challenge recipient changed

**Solutions:**
- Use recipient from challenge request parameters
- Decode challenge to get correct recipient:
  ```python
  request_params = decode_challenge_request(challenge)
  recipient = request_params['recipient']
  ```

#### 4. "Credential already used (replay attempt)"

**Causes:**
- Reusing credential from previous payment
- Race condition with concurrent requests

**Solutions:**
- Create new credential for each payment
- Use unique session IDs
- Implement proper error recovery

#### 5. "Transaction broadcast failed"

**Causes:**
- RPC endpoint unavailable
- Invalid transaction format
- Insufficient gas

**Solutions:**
- Check RPC endpoint connectivity
- Verify transaction is properly signed
- Ensure fee payer has sufficient balance

### Debug Mode

Enable verbose logging:

```bash
export LOG_LEVEL=DEBUG
python main.py
```

### Testing Payment Flow

Use the test script:

```bash
python test-full-flow.py
```

This tests:
- Challenge generation
- Credential creation and verification
- Full payment flow
- Error handling
- Replay prevention
- Challenge expiration
- Pricing calculation
- Session cleanup
- Receipt generation
- Multiple models

### Manual Testing

```bash
# Step 1: Get challenge
curl -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test", "duration_seconds": 5}'

# Step 2: Extract session_id and challenge from response

# Step 3: Create credential (use client-pay.py)
python client-pay.py --prompt "Test" --duration 5
```

## Client Integration

### Python Client

Use the provided `client-pay.py` script:

```bash
export CLIENT_PRIVATE_KEY="0x..."
python client-pay.py --prompt "A cat playing piano" --duration 5
```

### cURL Examples

See `docs/mpp-curl-examples.md` for detailed cURL examples.

### Custom Client Implementation

1. **Request Challenge**: Send POST without credentials
2. **Parse Challenge**: Extract from `WWW-Authenticate` header
3. **Create Transaction**: Sign ERC20 transfer with domain 0x76
4. **Create Credential**: Encode challenge + transaction
5. **Submit Payment**: Resend request with `Authorization: Payment` header
6. **Handle Response**: Check for 200 OK or error
7. **Poll Status**: Use job_id to check video generation status

## Support

For issues or questions:

1. Check logs for error details
2. Review this integration guide
3. Run test suite to verify setup
4. Check FAL API status
5. Verify Tempo Network connectivity

---

**Version**: 1.0.0  
**Last Updated**: 2026-03-26  
**MPP Specification**: https://paymentauth.org/
