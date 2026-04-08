# MPP + Tempo Implementation Plan

This document breaks down the MPP (Machine Payments Protocol) integration into incremental, testable phases.

---

## Overview

**Goal**: Integrate MPP payment protocol with Tempo blockchain for pay-per-use video generation API.

**Key Decisions**:
- ✅ Follow official MPP spec (not v0 simplified spec)
- ✅ Use `type="transaction"` credential type (server broadcasts)
- ✅ Server sponsors fees (pays gas on behalf of clients)
- ✅ Accept pathUSD (TIP-20 stablecoin) for payments
- ✅ HMAC-based challenge binding (stateless replay prevention)
- ✅ Test on Tempo testnet first

---

## Phase 1: Setup & Infrastructure

**Goal**: Get all infrastructure pieces ready for development and testing.

### Tasks

1. **Set up Tempo testnet access**
   - Add RPC endpoint to config
   - Test basic RPC connectivity
   - Document RPC endpoint in `.env.example`

2. **Generate server wallet**
   - Generate Ethereum keypair for server
   - Store private key in `.env` (never commit!)
   - Derive public address for receiving payments
   - Add wallet address to config

3. **Get test tokens from faucet**
   - Get test TEMP for gas fees
   - Get test pathUSD for payment testing
   - Verify balances via RPC

4. **Add dependencies**
   - Install `web3.py` for blockchain interactions
   - Install `eth-account` for transaction signing
   - Add to `requirements.txt`

### Deliverables

- `.env` with:
  - `TEMPO_RPC_URL` (testnet)
  - `SERVER_PRIVATE_KEY`
  - `SERVER_ADDRESS` (derived)
  - `PATHUSD_ADDRESS` (testnet contract)
  - `MPP_SECRET_KEY` (32-byte random for HMAC)

- `requirements.txt` updated with web3.py, eth-account

- Simple test script: `test-tempo-rpc.py`
  - Connects to RPC
  - Checks server balance
  - Prints "OK" if working

### Manual Testing

```bash
# Test RPC connection
python test-tempo-rpc.py

# Expected output:
# RPC: Connected
# Server Address: 0x...
# TEMP Balance: 1.5
# pathUSD Balance: 100.0
# OK
```

### Acceptance Criteria

- [ ] Can connect to Tempo testnet RPC
- [ ] Server wallet generated and funded
- [ ] Has both TEMP (gas) and pathUSD (payments)
- [ ] Dependencies installed

---

## Phase 2: Challenge Generation (402 Responses)

**Goal**: Server returns proper MPP challenges when payment is required.

### Tasks

1. **Create challenge generation module**
   - `mpp/challenge.py`
   - `create_challenge()` function with HMAC binding
   - JCS (JSON Canonicalization) for request encoding
   - Base64url encoding (no padding)
   - Proper expiry handling (5 minutes default)

2. **Update `/api/video/generate` endpoint**
   - Detect missing payment credential
   - Generate challenge with correct amount
   - Return 402 with `WWW-Authenticate: Payment` header
   - Include proper `Cache-Control: no-store`

3. **Add challenge formatting**
   - Format challenge params for HTTP header
   - Include all required fields (id, realm, method, intent, request, expires)
   - Proper quoting and escaping

### Deliverables

- `mpp/challenge.py` with:
  - `create_challenge(amount, recipient, realm, expires_in)`
  - `format_challenge_header(challenge)`
  - `decode_credential(auth_header)`

- Updated `generate_video()` endpoint

- Updated error response format (Problem Details per RFC 9457)

### Manual Testing

```bash
# Request without payment
curl -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "duration_seconds": 5}'

# Expected response:
# HTTP/1.1 402 Payment Required
# Cache-Control: no-store
# WWW-Authenticate: Payment id="abc123...",realm="api.example.com",method="tempo",intent="charge",request="eyJ...",expires="2025-..."
# Content-Type: application/problem+json
# {
#   "type": "https://paymentauth.org/problems/payment-required",
#   "title": "Payment Required",
#   "status": 402,
#   "detail": "This resource requires payment of $1.00 USD in pathUSD"
# }
```

### Acceptance Criteria

- [ ] Returns 402 status code
- [ ] Includes `WWW-Authenticate: Payment` header
- [ ] Challenge has HMAC-bound ID
- [ ] Request field is base64url-encoded JCS JSON
- [ ] Expiry is 5 minutes from now
- [ ] Response body uses Problem Details format

---

## Phase 3: Client Payment Script

**Goal**: Basic script to make payments (simulates client behavior).

### Tasks

1. **Create client script**
   - `client-pay.py`
   - Makes initial request, gets 402 challenge
   - Decodes challenge (parse header, base64url decode request)
   - Extracts: amount, currency, recipient, expires

2. **Create TIP-20 transfer transaction**
   - Encode `transfer(address,uint256)` function call
   - Set correct pathUSD contract address
   - Set recipient and amount from challenge
   - Set Tempo transaction type (0x76)
   - Set nonce, nonceKey, validBefore, fee_token

3. **Sign transaction locally**
   - Use secp256k1 (domain 0x76)
   - Leave fee_payer_signature as placeholder
   - Get raw transaction bytes

4. **Create credential**
   - Echo full challenge back
   - Include signed transaction in payload
   - Set `type: "transaction"`
   - Base64url encode entire credential

5. **Retry request with payment**
   - Add `Authorization: Payment <credential>` header
   - Send same request body
   - Parse response

### Deliverables

- `client-pay.py` script with:
  - Challenge decoding
  - Transaction creation
  - Local signing
  - Credential encoding
  - Payment retry

- `client-config.py` with:
  - `CLIENT_PRIVATE_KEY`
  - `RPC_URL`
  - `API_URL`

### Manual Testing

```bash
# Run client script
python client-pay.py

# Expected output:
# Step 1: Requesting video generation...
# Step 2: Got 402 challenge
#   Challenge ID: abc123...
#   Amount: $1.00 pathUSD
#   Recipient: 0x742d...
#   Expires: 2025-01-15T12:05:00Z
# Step 3: Creating TIP-20 transfer transaction...
# Step 4: Signing transaction locally...
# Step 5: Sending credential...
# Step 6: Got response: 200 OK (or 503 if server not ready)
# Transaction Hash: 0x...
```

### Acceptance Criteria

- [ ] Script can decode 402 challenge
- [ ] Creates valid TIP-20 transfer transaction
- [ ] Signs transaction locally (domain 0x76)
- [ ] Encodes credential with full challenge echo
- [ ] Retries request with `Authorization` header
- [ ] Prints transaction hash if successful

---

## Phase 4: Credential Verification

**Goal**: Server verifies payment credentials correctly.

### Tasks

1. **Parse incoming credential**
   - Extract `Authorization: Payment` header
   - Base64url decode credential
   - Extract challenge and payload

2. **Verify challenge binding**
   - Recompute HMAC from echoed challenge params
   - Verify challenge ID matches
   - Check expiry (not expired)

3. **Verify transaction signature**
   - Recover signer from transaction bytes
   - Verify secp256k1 signature (domain 0x76)

4. **Verify transfer parameters**
   - Decode transaction calldata
   - Extract recipient and amount from `transfer()` call
   - Verify recipient matches challenge
   - Verify amount >= challenge amount
   - Verify currency (pathUSD contract address)

5. **Check replay prevention**
   - Verify `validBefore` not in past
   - (Optional) Track used transaction hashes

### Deliverables

- `mpp/verify.py` with:
  - `verify_credential(auth_header, secret_key)`
  - `verify_challenge_binding(challenge, secret_key)`
  - `verify_transaction_signature(tx_bytes)`
  - `verify_transfer_params(tx_bytes, challenge)`

- Updated `generate_video()` endpoint:
  - Calls verification on payment requests
  - Returns 402 if verification fails
  - Proceeds to video generation if successful

### Manual Testing

```bash
# Test with valid credential (from client script)
python client-pay.py

# Expected server logs:
# INFO: Received credential
# INFO: Challenge binding valid
# INFO: Transaction signature valid
# INFO: Transfer params valid: recipient=0x742d..., amount=1000000
# INFO: Payment verified successfully

# Test with tampered credential (modify amount)
# Expected server logs:
# ERROR: Transfer params invalid: amount mismatch
# HTTP/1.1 402 Payment Required

# Test with expired credential (wait 6 minutes)
# Expected server logs:
# ERROR: Challenge expired
# HTTP/1.1 402 Payment Required
```

### Acceptance Criteria

- [ ] Can parse and decode credential
- [ ] Verifies HMAC binding (rejects tampered challenges)
- [ ] Verifies transaction signature
- [ ] Verifies transfer recipient and amount
- [ ] Rejects expired challenges
- [ ] Returns 402 on verification failure
- [ ] Proceeds to next step on success

---

## Phase 5: Fee Sponsorship & Broadcast

**Goal**: Server adds fee sponsorship and broadcasts transaction.

### Tasks

1. **Decode client transaction**
   - Parse RLP-encoded transaction
   - Extract fields (to, data, nonce, validBefore, etc.)

2. **Add fee sponsorship**
   - Set `fee_token` to pathUSD address
   - Sign as fee payer (domain 0x78)
   - Combine signatures (client + fee payer)

3. **Broadcast transaction**
   - Call `eth_sendRawTransaction` RPC
   - Get transaction hash
   - Log broadcast success/failure

4. **Handle broadcast errors**
   - Retry logic for transient failures
   - Return 503 if broadcast fails permanently
   - Log error details

5. **Generate payment receipt**
   - Create receipt object per MPP spec
   - Include: method, reference (tx hash), status, timestamp
   - Base64url encode receipt
   - Add `Payment-Receipt` header to response

### Deliverables

- `mpp/broadcast.py` with:
  - `add_fee_sponsorship(tx_bytes, fee_payer_key)`
  - `broadcast_transaction(signed_tx_bytes)`
  - `create_receipt(tx_hash, status)`

- Updated `generate_video()` endpoint:
  - Calls broadcast after verification
  - Returns 200 with receipt on success
  - Returns 503 on broadcast failure

### Manual Testing

```bash
# Run client script
python client-pay.py

# Expected output:
# Step 6: Got response: 200 OK
# Payment Receipt: eyJtZXRob2QiOiJ0ZW1wbyIsInJlZmVyZW5jZSI6IjB4YWJjMTIz...
# Transaction Hash: 0xabc123...

# Expected server logs:
# INFO: Added fee sponsorship (fee_token: pathUSD)
# INFO: Broadcast transaction: 0xabc123...
# INFO: Payment receipt generated

# Verify on blockchain explorer:
# - Transaction exists
# - pathUSD transferred from client to server
# - Fees paid by server (fee payer)
```

### Acceptance Criteria

- [ ] Server adds fee payer signature (domain 0x78)
- [ ] Sets fee_token to pathUSD
- [ ] Broadcasts transaction successfully
- [ ] Returns 200 with `Payment-Receipt` header
- [ ] Receipt contains tx hash
- [ ] pathUSD balance transferred on-chain
- [ ] Server fee balance decreased by gas cost

---

## Phase 6: Integration with Video Generation

**Goal**: Connect payment verification to actual video generation.

### Tasks

1. **Refactor payment flow**
   - Separate payment logic from business logic
   - Create payment middleware/decorator
   - Only call FAL API after payment verified

2. **Update payment amounts**
   - Calculate dynamic pricing based on duration
   - Include markup in challenge amount
   - Update challenge with correct amount

3. **Handle payment failures gracefully**
   - Don't charge if video generation fails
   - Consider refund mechanism (future)
   - Log payment vs generation failures separately

4. **Add payment tracking**
   - Log successful payments
   - Track revenue (pathUSD received)
   - Monitor fee balance

### Deliverables

- `mpp/middleware.py` with:
  - `require_payment(amount)` decorator
  - Integration with existing auth flow

- Updated `generate_video()` endpoint:
  - Calculates price from duration
  - Creates challenge with correct amount
  - Calls FAL API only after payment verified
  - Returns video job on success

- Payment logging/monitoring

### Manual Testing

```bash
# Full flow test
python client-pay.py

# Expected:
# - Payment verified
# - Video generation started
# - Job ID returned
# - Server received pathUSD

# Check server pathUSD balance increased
# Check fee balance decreased

# Verify video generation actually happens:
curl http://localhost:8000/api/video/jobs/<job_id>
# Should return job status
```

### Acceptance Criteria

- [ ] Payment verified before FAL API call
- [ ] Correct amount charged (based on duration)
- [ ] Video generation starts after payment
- [ ] Job ID returned to client
- [ ] Server pathUSD balance increased
- [ ] Fee balance decreased appropriately

---

## Phase 7: Testing & Hardening

**Goal**: Production-ready implementation with proper error handling.

### Tasks

1. **Error handling**
   - All RPC errors caught and logged
   - User-friendly error messages
   - Proper HTTP status codes (always 402 for payment failures)

2. **Logging & monitoring**
   - Log all payment attempts
   - Log verification failures (security monitoring)
   - Log broadcast failures
   - Track success/failure rates

3. **Security hardening**
   - Rate limiting on challenge requests
   - Validate all inputs
   - Secure private key handling
   - Audit HMAC implementation

4. **Documentation**
   - API documentation for clients
   - Example client code (multiple languages)
   - Troubleshooting guide

5. **Testing**
   - Unit tests for challenge generation
   - Unit tests for verification
   - Integration tests (full flow)
   - Test edge cases (expired challenges, insufficient funds, etc.)

### Deliverables

- Comprehensive error handling
- Logging throughout payment flow
- Security audit checklist
- Client documentation
- Test suite

### Manual Testing

```bash
# Test edge cases:
# 1. Expired challenge
# 2. Insufficient funds
# 3. Invalid signature
# 4. Tampered amount
# 5. Replay attack (reuse credential)
# 6. RPC unavailable
# 7. Broadcast failure

# All should return appropriate error responses
```

### Acceptance Criteria

- [ ] All errors handled gracefully
- [ ] Comprehensive logging
- [ ] Security review completed
- [ ] Client documentation written
- [ ] Test suite passes
- [ ] Ready for mainnet deployment

---

## Questions for User

Before starting implementation, I need answers to these questions:

### 1. Server Wallet Setup
- Do you already have a Tempo wallet/private key, or should I generate a new one?
- For testnet, should we use a temporary wallet (okay to lose) or your main wallet?

### 2. Pricing
- What's the base price per second for video generation?
- What markup percentage on top of FAL costs?
- Should pricing be configurable via environment variable?

### 3. RPC Provider
- Do you want to use a specific RPC provider, or should I use the public Tempo testnet RPC?
- Public testnet RPC: `https://rpc.testnet.tempo.xyz`

### 4. Fee Payer Setup
- Should fee sponsorship use the same wallet as payment recipient, or a separate fee payer wallet?
- (Same wallet is simpler for v0, separate is better for production)

### 5. Client Script Features
- Should the client script be interactive (prompts for input) or fully automated?
- Should it support both testnet and mainnet (via config)?
- Python only, or also need examples in other languages (JavaScript, curl)?

### 6. Testing Budget
- How much pathUSD should we get from faucet for testing?
- (Recommend: 100 pathUSD = enough for ~100 video generations at $1 each)

### 7. Deployment Timeline
- When do you want testnet deployment?
- When do you want mainnet deployment?

---

## Next Steps

1. **User answers questions above**
2. **Start Phase 1** (Setup & Infrastructure)
3. **Manual test after each phase**
4. **Iterate based on feedback**

---

## Estimated Timeline

| Phase | Estimated Time | Dependencies |
|-------|---------------|--------------|
| Phase 1: Setup | 1-2 hours | User answers questions |
| Phase 2: Challenges | 2-3 hours | Phase 1 complete |
| Phase 3: Client Script | 3-4 hours | Phase 2 complete |
| Phase 4: Verification | 3-4 hours | Phase 2 complete |
| Phase 5: Broadcast | 3-4 hours | Phase 4 complete |
| Phase 6: Integration | 2-3 hours | Phase 5 complete |
| Phase 7: Hardening | 4-6 hours | Phase 6 complete |

**Total**: 18-26 hours of development time

---

## File Structure

```
video-gen-mpp/
├── mpp/
│   ├── __init__.py
│   ├── challenge.py      # Phase 2
│   ├── verify.py         # Phase 4
│   ├── broadcast.py      # Phase 5
│   └── middleware.py     # Phase 6
├── client-pay.py         # Phase 3
├── test-tempo-rpc.py     # Phase 1
├── config.py             # Updated in Phase 1
├── main.py               # Updated throughout
├── .env                  # Phase 1 (never commit!)
├── .env.example          # Phase 1
└── docs/
    ├── mpp-v0-specs.md   # Original spec (keep for reference)
    ├── MPP-TEMPO-RESEARCH-EXPLAINED.md  # Research doc
    └── mpp-implementation-plan.md  # This document
```

---

## Success Metrics

- **Functional**: Full payment flow works end-to-end
- **Security**: HMAC binding prevents tampering
- **Performance**: <1 second payment verification
- **Cost**: Server fees <1% of revenue
- **UX**: Client can pay with single API call

---

*Last updated: 2026-03-25*
