# MPP + Tempo Protocol: Developer Guide

This document explains the Machine Payments Protocol (MPP) and Tempo blockchain implementation in simple terms for developers.

---

## Table of Contents

1. [MPP Challenge/Credential Flow](#1-mpp-challengecredential-flow)
2. [TIP-20 Transfers](#2-tip-20-transfers)
3. [Transaction vs Hash Credential Types](#3-transaction-vs-hash-credential-types)
4. [Fee Sponsorship](#4-fee-sponsorship)
5. [Common Token Choices](#5-common-token-choices)
6. [Replay Prevention Strategies](#6-replay-prevention-strategies)

---

## 1. MPP Challenge/Credential Flow

### What is a "challenge" in MPP protocol?

A **challenge** is the server's way of saying "pay this amount to access this resource." It's sent via the HTTP `WWW-Authenticate: Payment` header when the server responds with `402 Payment Required`.

**Simple analogy**: Think of it like a vending machine displaying the price. The challenge tells you:
- How much to pay
- Who to pay
- What payment method to use
- How long the price is valid

**Example challenge header:**
```http
HTTP/1.1 402 Payment Required
WWW-Authenticate: Payment 
    id="x7Tg2pLqR9mKvNwY3hBcZa",
    realm="api.example.com",
    method="tempo",
    intent="charge",
    expires="2025-01-15T12:05:00Z",
    request="eyJhbW91bnQiOiIxMDAwMDAwIiwiY3VycmVuY3kiOiIweDIwYzAw..."
```

### What is a "credential"?

A **credential** is the client's proof of payment. It's sent via the `Authorization: Payment` header on the retry request.

**Simple analogy**: This is like inserting money into the vending machine and getting a receipt. The credential proves you paid.

**Example credential header:**
```http
Authorization: Payment eyJjaGFsbGVuZ2UiOnsiaWQiOiJ4N1RnMnBMcVI5bUt2TndZM2hCY1phIi ...
```

When decoded, the credential contains:
```json
{
  "challenge": {
    "id": "x7Tg2pLqR9mKvNwY3hBcZa",
    "realm": "api.example.com",
    "method": "tempo",
    "intent": "charge",
    "request": "eyJhbW91bnQiOiIxMDAwMDAwIiwiY3VycmVuY3kiOiIweDIwYzAw...",
    "expires": "2025-01-15T12:05:00Z"
  },
  "payload": {
    "signature": "0x76f901...",
    "type": "transaction"
  }
}
```

### Simplified v0 Spec vs Official MPP Spec

Your current implementation (`docs/mpp-v0-specs.md`) uses a **simplified approach**:

| Aspect | Your v0 Spec (Simplified) | Official MPP Spec |
|--------|--------------------------|-------------------|
| **Challenge format** | Server returns JSON body with payment info | Server uses `WWW-Authenticate: Payment` header with structured parameters |
| **Credential format** | Simple base64 JSON: `{"tx_hash": "0xabc...", "chain_id": "tempo-testnet"}` | Full challenge echo with payload: `{"challenge": {...}, "payload": {...}}` |
| **Challenge binding** | None - server must track challenges in memory/database | HMAC-signed challenge `id` binds all parameters together |
| **Security** | Basic - relies on tx_hash uniqueness | Strong - cryptographic binding prevents tampering |
| **State** | Stateful (server tracks used transactions) | Can be stateless (HMAC verification) |

**Your v0 approach:**
```python
# Server returns JSON body
{
  "amount": 0.001,
  "currency": "USDC",
  "recipient": "0xYourAddress",
  "chain_id": "tempo-testnet"
}

# Client sends back
Authorization: Payment eyJ0eF9oYXNoIjoiMHhhYmMuLi4ifQ==
# Decodes to: {"tx_hash": "0xabc...", "chain_id": "tempo-testnet"}
```

**Official MPP approach:**
```python
# Server returns header
WWW-Authenticate: Payment 
    id="kM9xPqWvT2nJrHsY4aDfEb",
    realm="api.example.com",
    method="tempo",
    intent="charge",
    request="eyJhbW91bnQiOiIxMDAwMDAwIiwiY3VycmVuY3kiOiIweDIwYzAw..."

# Client sends back full challenge echo
Authorization: Payment eyJjaGFsbGVuZ2UiOnsiaWQiOiJrTTl4UHFXdlQybkpySHNZNGFEZkViIi...
# Decodes to:
{
  "challenge": {
    "id": "kM9xPqWvT2nJrHsY4aDfEb",
    "realm": "api.example.com",
    "method": "tempo",
    "intent": "charge",
    "request": "eyJhbW91bnQiOiIxMDAwMDAwIiwiY3VycmVuY3kiOiIweDIwYzAw..."
  },
  "payload": {
    "signature": "0x76f901...",
    "type": "transaction"
  }
}
```

### What does "base64url-encoded challenge" mean and why is it used?

**Base64url encoding** is a URL-safe variant of base64 encoding that:
- Uses `-` instead of `+`
- Uses `_` instead of `/`
- Omits padding `=` characters

**Why it's used:**
1. **HTTP header safe**: No special characters that need escaping
2. **Compact**: Shorter than hex encoding
3. **Standard**: Defined in RFC 4648 for web use cases
4. **No URL encoding needed**: Can be used directly in URLs and headers

**Example:**
```python
import base64
import json

# Original JSON
request = {
    "amount": "1000000",
    "currency": "0x20c0000000000000000000000000000000000000",
    "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE00"
}

# JSON Canonicalization (JCS) - ensures consistent ordering
json_str = json.dumps(request, separators=(',', ':'), sort_keys=True)

# Base64url encode (no padding)
encoded = base64.urlsafe_b64encode(json_str.encode()).decode().rstrip('=')
# Result: "eyJhbW91bnQiOiIxMDAwMDAwIiwiY3VycmVuY3kiOiIweDIwYzAw..."
```

### What is "full challenge echo" and why is it needed for security?

**Full challenge echo** means the client must include the COMPLETE challenge data in the credential, not just a reference.

**Why it's needed:**

1. **Tamper prevention**: Server can verify the client didn't modify challenge parameters
2. **Stateless verification**: Server doesn't need to store challenges - can recompute expected values
3. **Binding**: Prevents "challenge substitution" attacks where a client tries to use a cheaper challenge

**Without challenge echo (vulnerable):**
```
Server sends: "Pay $10 to address A"
Client pays: $1 to address B
Client claims: "I paid!" (sends only tx_hash)
Server must: Look up original challenge from database
```

**With challenge echo (secure):**
```
Server sends: Challenge with id=HMAC(params)
Client echoes: Full challenge + payment proof
Server verifies: 
  1. Recompute HMAC from echoed params
  2. Check id matches
  3. Verify payment matches echoed params
```

**Security flow:**
```python
# Server creates challenge
realm = "api.example.com"
amount = "1000000"
recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE00"

# Create deterministic request JSON (JCS)
request_json = json.dumps({
    "amount": amount,
    "currency": "0x20c0000000000000000000000000000000000000",
    "recipient": recipient
}, separators=(',', ':'), sort_keys=True)

request_b64 = base64.urlsafe_b64encode(request_json.encode()).decode().rstrip('=')

# Compute HMAC-SHA256 binding
hmac_input = f"{realm}|tempo|charge|{request_b64}||"
challenge_id = base64.urlsafe_b64encode(
    hmac.new(secret_key, hmac_input.encode(), hashlib.sha256).digest()
).decode().rstrip('=')

# Client must echo back EXACTLY this data
# Server recomputes and verifies match
```

---

## 2. TIP-20 Transfers

### What is TIP-20 token standard?

**TIP-20** is Tempo's native token standard, similar to ERC-20 but with important enhancements built directly into the blockchain as **precompiled contracts** (not smart contracts).

**Key features:**
- 6 decimal places (like USDC)
- Built-in memo fields for payment reconciliation
- Native gas payment (no need for separate gas token)
- Role-based access control
- Built-in reward distribution
- Transfer policies for compliance

### How is it different from native token transfers?

| Aspect | Native TEMP Transfer | TIP-20 Transfer |
|--------|---------------------|-----------------|
| **Token type** | Native chain token (like ETH) | Token standard (like ERC-20) |
| **Gas payment** | Always used for fees | Can be used for fees (any TIP-20 stablecoin) |
| **Memo support** | No | Yes - 32-byte memo on transfers |
| **Implementation** | Protocol-level | Precompiled contract |
| **Standard functions** | Basic transfer | `transfer`, `transferWithMemo`, `approve`, `transferFrom` |
| **Use case** | Transaction fees | Stablecoins, application tokens |

**Native TEMP transfer:**
```python
# Simple value transfer (like ETH)
tx = {
    "to": "0xRecipient",
    "value": w3.to_wei(1.0, "ether"),  # Native TEMP
    "gas": 21000,
    "nonce": nonce,
}
```

**TIP-20 transfer:**
```python
# Token contract interaction (like ERC-20)
# Calls transfer() on the TIP-20 precompile
tx = {
    "to": "0xTIP20TokenAddress",
    "value": 0,  # No native value
    "data": "0xa9059cbb" + encode_address(recipient) + encode_amount(1000000),  # transfer()
    "gas": 50000,
    "fee_token": "0xTIP20StablecoinAddress",  # Pay fees in this token
}
```

### Is it like a voucher system or more like ERC-20?

**TIP-20 is like ERC-20** - it's a token standard with balances, transfers, and approvals.

**Vouchers are different** - they're off-chain promises to pay, used in MPP's **session intent**:

| Concept | Description |
|---------|-------------|
| **TIP-20** | On-chain token (like ERC-20) with balances and transfers |
| **Voucher** | Off-chain signed message authorizing payment from a pre-funded channel |
| **Charge** | Direct TIP-20 transfer (one-time payment) |
| **Session** | Payment channel with vouchers (streaming/metered payments) |

**Analogy:**
- **TIP-20** = Cash in your wallet
- **Voucher** = Writing a check against your bank account
- **Channel** = Your bank account (holds the funds)
- **Charge** = Handing over cash
- **Session** = Writing multiple checks over time against the same account

### Example Transaction Data

#### Native TEMP Transfer (NOT used for MPP payments)
```python
# Client sends native TEMP (rarely used for payments)
tx = {
    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE00",
    "value": w3.to_wei(0.001, "ether"),  # 0.001 TEMP
    "gas": 21000,
    "nonce": w3.eth.get_transaction_count(account.address),
    "chainId": 42431,
}

signed = account.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
```

#### TIP-20 Transfer (Charge Intent - One-Time Payment)
```python
# For MPP charge intent, client creates a Tempo Transaction
# that calls transfer() or transferWithMemo() on TIP-20 token

from web3 import Web3

# Encode transfer function call
transfer_selector = "0xa9059cbb"  # transfer(address,uint256)
recipient_encoded = Web3.to_hex(Web3.to_bytes(hexstr=recipient)).rjust(64, '0')
amount_encoded = Web3.to_hex(Web3.to_bytes(amount)).rjust(64, '0')

calldata = transfer_selector + recipient_encoded + amount_encoded

# Tempo Transaction (type 0x76)
tx = {
    "type": 0x76,  # Tempo transaction type
    "to": "0x20c0000000000000000000000000000000000000",  # TIP-20 token address
    "value": 0,
    "data": calldata,
    "chainId": 42431,
    "nonce": 123,
    "nonceKey": 1,  # 2D nonce lane for payments
    "validBefore": 1736165100,  # Challenge expiry timestamp
    "fee_token": "0x20c0000000000000000000000000000000000000",  # Pay fees in same token
    # If feePayer=true, these are placeholders:
    "fee_payer_signature": "0x00",
}

# Sign with secp256k1 (domain 0x76)
signed = account.sign_transaction(tx)
tx_bytes = signed.rawTransaction.hex()

# Credential payload
credential = {
    "challenge": {...},  # Echo challenge
    "payload": {
        "signature": tx_bytes,  # Full RLP-encoded signed transaction
        "type": "transaction"
    }
}
```

#### TIP-20 with Memo (for reconciliation)
```python
# transferWithMemo function
transfer_with_memo_selector = "0x..."  # Specific selector
memo = Web3.keccak(text="invoice-123")  # 32-byte memo

calldata = transfer_with_memo_selector + \
           recipient_encoded + \
           amount_encoded + \
           memo.hex()
```

---

## 3. Transaction vs Hash Credential Types

### `type="transaction"` - What the client sends

When `type="transaction"`, the client sends a **signed but unbroadcast transaction**.

**What the client sends:**
```json
{
  "challenge": {...},
  "payload": {
    "signature": "0x76f901...RLP-encoded signed transaction bytes...",
    "type": "transaction"
  }
}
```

**Key points:**
- This is the **complete signed transaction** (RLP-encoded)
- Transaction is NOT yet on-chain
- Server receives the raw signed bytes
- Server can verify, modify (add fee sponsorship), and broadcast

**Does client interact with blockchain?**
- **NO direct broadcast** - client signs locally
- Client does NOT call `eth_sendRawTransaction`
- Client does NOT wait for confirmation
- Server handles broadcasting

### `type="hash"` - What the client sends

When `type="hash"`, the client has **already broadcast** the transaction.

**What the client sends:**
```json
{
  "challenge": {...},
  "payload": {
    "hash": "0x1a2b3c4d5e6f7890abcdef...",
    "type": "hash"
  }
}
```

**Key points:**
- This is just the **transaction hash** (txid)
- Transaction IS already on-chain
- Server must verify via RPC: `eth_getTransactionReceipt`
- Server cannot modify the transaction

**Does client interact with blockchain?**
- **YES** - client broadcasts before sending credential
- Client calls `eth_sendRawTransaction`
- Client waits for confirmation (optional but recommended)
- Client then sends hash to server

### Does client need to interact with blockchain directly?

| Credential Type | Client Broadcasts? | Server Broadcasts? | Blockchain Interaction |
|----------------|-------------------|-------------------|----------------------|
| `type="transaction"` | NO | YES | Client signs only; server broadcasts |
| `type="hash"` | YES | NO | Client signs AND broadcasts; server verifies |

### What does "server broadcasting" mean?

**Server broadcasting** means the server takes the signed transaction from the credential and submits it to the blockchain network.

**Flow for `type="transaction"`:**
```
1. Client signs transaction locally
2. Client sends signed bytes to server in credential
3. Server verifies signature and parameters
4. Server calls eth_sendRawTransaction(signed_tx)
5. Transaction enters the mempool
6. Validators include it in a block
7. Server gets tx_hash back
8. Server returns receipt to client
```

**Why server broadcasting?**
- Enables **fee sponsorship** (server adds fee payer signature)
- Server can verify before committing to broadcast
- Better error handling
- Server controls timing

### Step-by-Step Flow Diagrams

#### Flow A: `type="transaction"` (Recommended for fee sponsorship)

```
┌─────────────┐                    ┌─────────────┐                 ┌──────────────┐
│   Client    │                    │   Server    │                 │Tempo Network │
└─────────────┘                    └─────────────┘                 └──────────────┘
       │                                 │                                │
       │  (1) GET /api/resource          │                                │
       │────────────────────────────────>│                                │
       │                                 │                                │
       │  (2) 402 Payment Required       │                                │
       │      WWW-Authenticate: Payment  │                                │
       │      (challenge with request)   │                                │
       │<────────────────────────────────│                                │
       │                                 │                                │
       │  (3) Build Tempo Transaction    │                                │
       │      - Set transfer() call      │                                │
       │      - Set validBefore          │                                │
       │      - Set fee_payer_signature  │                                │
       │        = 0x00 (placeholder)     │                                │
       │                                 │                                │
       │  (4) Sign transaction locally   │                                │
       │      (DOES NOT BROADCAST)       │                                │
       │                                 │                                │
       │  (5) Authorization: Payment     │                                │
       │      {                          │                                │
       │        "challenge": {...},      │                                │
       │        "payload": {             │                                │
       │          "signature": "0x76...",│                                │
       │          "type": "transaction"  │                                │
       │        }                        │                                │
       │      }                          │                                │
       │────────────────────────────────>│                                │
       │                                 │                                │
       │                                 │ (6) Verify signature           │
       │                                 │     - Check transfer params    │
       │                                 │     - Check amount/recipient   │
       │                                 │                                │
       │                                 │ (7) If feePayer=true:          │
       │                                 │     - Add fee_payer_signature  │
       │                                 │     - Set fee_token            │
       │                                 │                                │
       │                                 │ (8) eth_sendRawTransaction     │
       │                                 │───────────────────────────────>│
       │                                 │                                │
       │                                 │ (9) Transaction included       │
       │                                 │     (~500ms finality)          │
       │                                 │<───────────────────────────────│
       │                                 │                                │
       │  (10) 200 OK                    │                                │
       │      Payment-Receipt: {...}     │                                │
       │      {txHash: "0xabc..."}       │                                │
       │<────────────────────────────────│                                │
       │                                 │                                │
```

#### Flow B: `type="hash"` (Client broadcasts first)

```
┌─────────────┐                    ┌─────────────┐                 ┌──────────────┐
│   Client    │                    │   Server    │                 │Tempo Network │
└─────────────┘                    └─────────────┘                 └──────────────┘
       │                                 │                                │
       │  (1) GET /api/resource          │                                │
       │────────────────────────────────>│                                │
       │                                 │                                │
       │  (2) 402 Payment Required       │                                │
       │      WWW-Authenticate: Payment  │                                │
       │<────────────────────────────────│                                │
       │                                 │                                │
       │  (3) Build & Sign Transaction   │                                │
       │      - Must set fee_token       │                                │
       │      - Client pays own fees     │                                │
       │                                 │                                │
       │  (4) eth_sendRawTransaction     │                                │
       │─────────────────────────────────────────────────────────────────>│
       │                                 │                                │
       │  (5) Transaction confirmed      │                                │
       │<─────────────────────────────────────────────────────────────────│
       │                                 │                                │
       │  (6) Authorization: Payment     │                                │
       │      {                          │                                │
       │        "challenge": {...},      │                                │
       │        "payload": {             │                                │
       │          "hash": "0x1a2b...",   │                                │
       │          "type": "hash"         │                                │
       │        }                        │                                │
       │      }                          │                                │
       │────────────────────────────────>│                                │
       │                                 │                                │
       │                                 │ (7) eth_getTransactionReceipt  │
       │                                 │───────────────────────────────>│
       │                                 │                                │
       │                                 │ (8) Verify receipt             │
       │                                 │     - Check Transfer event     │
       │                                 │     - Verify amount/recipient  │
       │                                 │<───────────────────────────────│
       │                                 │                                │
       │  (9) 200 OK                     │                                │
       │      Payment-Receipt: {...}     │                                │
       │<────────────────────────────────│                                │
       │                                 │                                │
```

**Key Differences:**

| Aspect | `type="transaction"` | `type="hash"` |
|--------|---------------------|---------------|
| **Fee sponsorship** | ✅ Supported | ❌ Not supported |
| **Server control** | High - can verify first | Low - must trust client |
| **Client complexity** | Lower - just sign | Higher - must broadcast & wait |
| **Latency** | Server controls timing | Client waits for confirmation |
| **DoS risk** | Server can reject before broadcast | Client already paid gas |
| **Use case** | Recommended for most APIs | When client wants immediate finality proof |

---

## 4. Fee Sponsorship

### What is fee sponsorship in Tempo?

**Fee sponsorship** allows the server to pay transaction fees on behalf of the client. The client only signs the payment authorization, while the server covers the gas cost.

**Analogy**: Like a store offering "free shipping" - the customer pays for the product, but the store covers the delivery cost.

### How does it work technically?

Tempo Transactions (type 0x76) support **dual signatures**:

1. **Client signature** (domain 0x76): Authorizes the payment transfer
2. **Server fee_payer_signature** (domain 0x78): Commits to pay fees

**Technical flow:**

```python
# Step 1: Client signs with placeholder
tx = {
    "type": 0x76,
    "to": token_address,
    "data": transfer_calldata,
    "fee_token": "",  # Empty - server will fill
    "fee_payer_signature": "0x00",  # Placeholder
    # ... other fields
}
client_signed = client.sign(tx)  # Domain 0x76

# Step 2: Server receives credential
signed_tx_bytes = credential["payload"]["signature"]

# Step 3: Server adds fee payer signature
server_selects_fee_token = "0x20c0000000000000000000000000000000000000"  # pathUSD
fee_payer_sig = server.sign(tx, domain=0x78)  # Domain 0x78

# Step 4: Combine signatures
final_tx = combine_signatures(client_signed, fee_payer_sig, server_selects_fee_token)

# Step 5: Server broadcasts
tx_hash = w3.eth.send_raw_transaction(final_tx)
```

**Key insight**: The client signs with an empty `fee_token` and placeholder signature. The server fills these in and adds its own signature domain (0x78).

### What's the typical/standard model?

**Most MPP/Tempo services use fee sponsorship** for better UX:

| Model | Description | Typical Use Case |
|-------|-------------|------------------|
| **Server sponsors** | Server pays fees | ✅ Most APIs, consumer-facing services |
| **Client pays** | Client pays fees | B2B, high-value transactions, crypto-native users |
| **Hybrid** | Server sponsors up to limit, then client pays | Freemium models |

**Why server sponsorship is common:**
1. **Better UX**: Users don't need to hold fee tokens
2. **Abstracts complexity**: No need to explain gas fees
3. **Predictable costs**: Server can bake fees into pricing
4. **Competitive**: Expected for consumer APIs

### Pros/Cons of Each Approach

#### Server Sponsors Fees

**Pros:**
- ✅ Seamless UX - users just pay the service fee
- ✅ No friction - users don't need separate fee tokens
- ✅ Server controls fee token choice (can optimize costs)
- ✅ Can batch settlements for efficiency
- ✅ Better for microtransactions (fees don't dominate)

**Cons:**
- ❌ Server bears cost risk
- ❌ DoS vulnerability - malicious clients can waste fee budget
- ❌ Need to monitor fee token balance
- ❌ More complex server implementation

#### Client Pays Fees

**Pros:**
- ✅ No cost to server
- ✅ No DoS risk from fake payments
- ✅ Simpler server logic
- ✅ Client has full control

**Cons:**
- ❌ Poor UX - users need multiple tokens
- ❌ Friction - must explain gas fees
- ❌ Higher barrier to entry
- ❌ Not suitable for microtransactions

### Examples from Other MPP Implementations

From the **mppx** SDK (TypeScript reference implementation):

```typescript
// Server-side fee sponsorship setup
import { Mppx, tempo } from 'mppx/server'

const mppx = Mppx.create({
  methods: [
    tempo({
      currency: '0x20c0000000000000000000000000000000000000',
      recipient: '0x742d35Cc6634c0532925a3b844Bc9e7595F8fE00',
      feePayer: true,  // Server sponsors fees
    }),
  ],
})

// Handler automatically adds fee_payer_signature
export async function handler(request: Request) {
  const response = await mppx.charge({ amount: '1' })(request)
  
  if (response.status === 402) return response.challenge
  
  return response.withReceipt(Response.json({ data: '...' }))
}
```

**Fee Payer Service** (separate microservice pattern):

```typescript
// Dedicated fee payer service
import { Handler } from 'mppx/server'

const feePayerHandler = Handler.feePayer({
  account: privateKeyToAccount(process.env.FEE_PAYER_KEY),
  allowedTokens: [
    '0x20c0000000000000000000000000000000000000', // pathUSD
    '0x...', // AlphaUSD
  ],
  maxFeePerDay: '100000000', // 100 USD daily limit
})

// Run as separate service
app.post('/api/fee-payer', feePayerHandler)
```

---

## 5. Common Token Choices

### What tokens do most MPP/Tempo services accept?

**Stablecoins dominate** - nearly all MPP services use USD-pegged TIP-20 tokens.

### Native TEMP vs Stablecoins - What's Typical?

| Token Type | Usage | Typical For |
|------------|-------|-------------|
| **USD Stablecoins** | ✅ Primary payment token | 95%+ of MPP services |
| **Native TEMP** | ❌ Transaction fees only | Not used for payments |

**Why stablecoins?**
1. **Price stability** - API pricing in USD makes sense
2. **User familiarity** - Everyone understands $1
3. **Accounting** - Easy to track revenue in USD
4. **No volatility risk** - Server doesn't hold volatile assets

### Common TIP-20 Stablecoins on Tempo

| Token | Address | Description |
|-------|---------|-------------|
| **pathUSD** | `0x20c0000000000000000000000000000000000000` | Native Tempo stablecoin (most common) |
| **AlphaUSD** | Various | Issued by Alpha Finance |
| **BetaUSD** | Various | Issued by Beta Finance |
| **USDC** | Bridge required | Bridged from other chains |

### Real-World Examples

From **mppx examples** and Tempo documentation:

**Example 1: AI API (charge intent)**
```typescript
// Pricing in USD, settled in pathUSD
const charge = mppx.charge({ 
  amount: '0.05',  // $0.05 USD
  currency: '0x20c0000000000000000000000000000000000000'  // pathUSD
})
```

**Example 2: LLM Streaming (session intent)**
```typescript
// Per-token pricing in pathUSD base units
const session = mppx.session({
  amount: '25',  // 0.000025 pathUSD per token
  unitType: 'llm_token',
  currency: '0x20c0000000000000000000000000000000000000',
  suggestedDeposit: '10000000',  // 10 pathUSD deposit
})
```

**Example 3: Multi-currency support**
```typescript
// Accept multiple stablecoins
const mppx = Mppx.create({
  methods: [
    tempo({
      currency: '0x20c0000000000000000000000000000000000000', // pathUSD
      recipient: serverAddress,
      feePayer: true,
      allowedFeeTokens: [
        '0x20c0000000000000000000000000000000000000', // pathUSD
        '0x...', // AlphaUSD
        '0x...', // BetaUSD
      ],
    }),
  ],
})
```

---

## 6. Replay Prevention Strategies

### How do other MPP implementations prevent replay attacks?

**Multiple layers of protection:**

#### 1. Transaction Nonces (Tempo's 2D Nonce System)

Tempo uses **2D nonces** with multiple "lanes":
```python
# Each account has multiple nonce keys
nonce_key = 1  # Dedicated lane for payments
nonce = get_next_nonce(account, nonce_key)

tx = {
    "nonce": nonce,
    "nonceKey": nonce_key,
    # ...
}
```

**Benefits:**
- Payment transactions don't block other account activity
- Parallel transaction submission
- Natural replay prevention (nonce consumed on-chain)

#### 2. Challenge Expiry

Every challenge has an `expires` timestamp:
```python
challenge = {
    "expires": "2025-01-15T12:05:00Z",
    # ...
}

# Client MUST set validBefore in transaction
tx = {
    "validBefore": 1736165100,  # Unix timestamp
}
```

**Server verifies:**
```python
if datetime.now() > challenge.expires:
    return error("Challenge expired")
```

#### 3. Challenge ID Binding

Official MPP spec uses HMAC to bind challenge ID to parameters:
```python
# Server computes
hmac_input = f"{realm}|{method}|{intent}|{request_b64}|{expires}|{digest}|{opaque}"
challenge_id = HMAC_SHA256(secret_key, hmac_input)

# Server verifies (stateless)
recomputed_id = HMAC_SHA256(secret_key, echoed_params)
if challenge_id != echoed_id:
    return error("Invalid challenge binding")
```

#### 4. Transaction Hash Tracking (Your v0 Approach)

```python
USED_TXS = set()

def verify_payment(tx_hash):
    if tx_hash in USED_TXS:
        return False  # Replay detected!
    
    # Verify on-chain...
    USED_TXS.add(tx_hash)
    return True
```

**Limitations:**
- Requires stateful storage
- Memory grows unbounded (need cleanup)
- Doesn't work across server restarts without database

#### 5. Channel-Based (Session Intent)

For streaming payments:
```python
# Each channel tracks cumulative settlement
channel = {
    "channelId": "0x...",
    "settled": 500000,  # Already withdrawn
    "deposit": 1000000,  # Total deposited
}

# Voucher must be monotonically increasing
if voucher.cumulativeAmount <= channel.settled:
    return error("Voucher not increasing")
```

### What's Recommended for Stateless Applications?

**Recommended approach: HMAC Challenge Binding + Expiry**

```python
import hmac
import hashlib
import base64
from datetime import datetime, timedelta

class StatelessMPPServer:
    def __init__(self, secret_key):
        self.secret_key = secret_key
    
    def create_challenge(self, amount, recipient, realm="api"):
        # Create deterministic request
        request = {
            "amount": str(amount),
            "currency": "0x20c0000000000000000000000000000000000000",
            "recipient": recipient.lower(),
        }
        request_json = json.dumps(request, separators=(',', ':'), sort_keys=True)
        request_b64 = base64.urlsafe_b64encode(request_json.encode()).decode().rstrip('=')
        
        # Expiry
        expires = (datetime.utcnow() + timedelta(minutes=5)).isoformat() + "Z"
        
        # HMAC binding (stateless!)
        hmac_input = f"{realm}|tempo|charge|{request_b64}|{expires}||"
        challenge_id = base64.urlsafe_b64encode(
            hmac.new(self.secret_key, hmac_input.encode(), hashlib.sha256).digest()
        ).decode().rstrip('=')
        
        return {
            "id": challenge_id,
            "realm": realm,
            "method": "tempo",
            "intent": "charge",
            "request": request_b64,
            "expires": expires,
        }
    
    def verify_credential(self, credential):
        challenge = credential["challenge"]
        
        # 1. Verify expiry
        if datetime.fromisoformat(challenge["expires"].rstrip("Z")) < datetime.utcnow():
            return False, "Challenge expired"
        
        # 2. Verify HMAC binding (stateless!)
        hmac_input = f"{challenge['realm']}|{challenge['method']}|{challenge['intent']}|{challenge['request']}|{challenge['expires']}||"
        expected_id = base64.urlsafe_b64encode(
            hmac.new(self.secret_key, hmac_input.encode(), hashlib.sha256).digest()
        ).decode().rstrip('=')
        
        if challenge["id"] != expected_id:
            return False, "Invalid challenge binding"
        
        # 3. Verify transaction (for type="transaction")
        if credential["payload"]["type"] == "transaction":
            tx = decode_transaction(credential["payload"]["signature"])
            
            # Check validBefore
            if tx.validBefore < datetime.utcnow().timestamp():
                return False, "Transaction expired"
            
            # Verify transfer params match challenge
            request = json.loads(base64.urlsafe_b64decode(challenge["request"] + "=="))
            if tx.recipient != request["recipient"]:
                return False, "Recipient mismatch"
            if tx.amount != request["amount"]:
                return False, "Amount mismatch"
        
        return True, "Valid"
```

**Benefits:**
- ✅ No database needed
- ✅ No state to manage
- ✅ Cryptographically secure
- ✅ Works across server restarts
- ✅ Prevents all replay vectors

### How Does Tempo's Nonce System Work?

**2D Nonce System:**

Traditional nonces (Ethereum):
```
Account 0x123: nonce=5
→ Must wait for nonce 5 to confirm before sending nonce 6
→ Sequential bottleneck
```

Tempo 2D nonces:
```
Account 0x123:
  nonce_key=0, nonce=10  # General transactions
  nonce_key=1, nonce=5   # Payment transactions
  nonce_key=2, nonce=2   # NFT transactions

→ Can send payment (key=1, nonce=5) without waiting for general (key=0, nonce=10)
→ Parallel lanes
```

**Implementation:**
```python
# Client dedicates a lane for MPP payments
PAYMENT_NONCE_KEY = 1

def create_payment_tx():
    # Get next nonce in payment lane
    nonce = get_nonce(account, PAYMENT_NONCE_KEY)
    
    tx = {
        "nonce": nonce,
        "nonceKey": PAYMENT_NONCE_KEY,
        "validBefore": int(time.time()) + 300,  # 5 min window
        # ...
    }
    return tx
```

**Replay prevention:**
- Each (account, nonceKey, nonce) tuple is unique
- Once used, cannot be reused
- `validBefore` adds time-bound protection

### Best Practices Summary

1. **Use HMAC challenge binding** (stateless, secure)
2. **Set short expiry** (5-15 minutes typical)
3. **Dedicate nonce lane** for payments (nonceKey=1)
4. **Set validBefore** in transactions
5. **Verify on-chain** before granting access
6. **Track used tx hashes** (optional, defense in depth)
7. **Rate limit** per client/IP (prevent DoS)
8. **Use `type="transaction"`** for fee sponsorship control

```python
# Complete replay prevention checklist
def verify_payment_comprehensive(credential):
    checks = [
        verify_challenge_expiry(credential),
        verify_hmac_binding(credential),
        verify_transaction_signature(credential),
        verify_transfer_params(credential),
        verify_valid_before(credential),
        verify_nonce_not_used(credential),  # Optional
        verify_onchain_not_settled(credential),  # For sessions
    ]
    
    if not all(checks):
        return False
    return True
```

---

## Quick Reference

### Header Format Cheat Sheet

```http
# Challenge (Server → Client)
WWW-Authenticate: Payment 
    id="x7Tg2pLqR9mKvNwY3hBcZa",
    realm="api.example.com",
    method="tempo",
    intent="charge",
    request="eyJhbW91bnQiOiIxMDAwMDAwIiwiY3VycmVuY3kiOiIweDIwYzAw...",
    expires="2025-01-15T12:05:00Z"

# Credential (Client → Server)
Authorization: Payment eyJjaGFsbGVuZ2UiOnsiaWQiOiJ4N1RnMnBMcVI5bUt2TndZM2hCY1phIi...

# Receipt (Server → Client on success)
Payment-Receipt: eyJtZXRob2QiOiJ0ZW1wbyIsInJlZmVyZW5jZSI6IjB4YWJjMTIzIiwic3RhdHVzIjoic3VjY2VzcyIsInRpbWVzdGFtcCI6IjIwMjUtMDEtMTVUMTI6MDA6MDBaIn0
```

### Common Values

| Parameter | Typical Value |
|-----------|--------------|
| `method` | `"tempo"` |
| `intent` | `"charge"` (one-time) or `"session"` (streaming) |
| `currency` | `"0x20c0000000000000000000000000000000000000"` (pathUSD) |
| `chainId` | `42431` (Moderato testnet) or `424` (mainnet) |
| `expires` | 5-15 minutes from now |
| `nonceKey` | `1` (dedicated payment lane) |

### Error Codes

| Status | Meaning | Action |
|--------|---------|--------|
| 402 | Payment required | Send payment credential |
| 400 | Malformed credential | Fix format, retry |
| 403 | Payment valid but access denied | Contact server admin |
| 503 | Service unavailable | Retry later |

---

## Resources

- **Official MPP Spec**: https://github.com/tempoxyz/mpp-specs
- **IETF Draft**: https://datatracker.ietf.org/doc/draft-ryan-httpauth-payment/
- **Tempo Docs**: https://docs.tempo.xyz
- **mppx SDK**: https://github.com/wevm/mppx
- **TIP-20 Spec**: https://docs.tempo.xyz/protocol/tip20/spec

