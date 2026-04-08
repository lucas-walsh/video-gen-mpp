# MPP Module Usage Guide

## Overview

The MPP (Machine Payments Protocol) modules provide complete payment authentication for the Tempo blockchain.

## Modules

### 1. `mpp.challenge` - Challenge Generation

```python
from mpp.challenge import (
    create_challenge,
    format_challenge_header,
    verify_challenge_binding,
    base64url_encode,
    base64url_decode,
    jcs_encode,
    jcs_decode,
)

# Create a challenge
challenge = create_challenge(
    amount=1.50,                          # Payment amount in USD
    recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",  # Server address
    realm="video-gen-api",                # Realm identifier
    method="tempo",                       # Payment method
    currency="pathUSD",                   # Currency name
    currency_address="0x20c0000000000000000000000000000000000000",  # TIP-20 contract
    expires_in=300,                       # Expiry in seconds (5 minutes)
    secret_key="your_mpp_secret_key"      # HMAC secret
)

# Format as WWW-Authenticate header
header_value = format_challenge_header(challenge)
# Returns: 'Payment realm="video-gen-api",id="...",method="tempo",...'

# Verify challenge HMAC binding
is_valid = verify_challenge_binding(challenge, secret_key)
```

### 2. `mpp.credential` - Credential Verification

```python
from mpp.credential import (
    parse_authorization_header,
    verify_credential,
    verify_transfer_parameters,
    check_replay_prevention,
)

# Parse Authorization header
credential_data = parse_authorization_header(auth_header)
# Returns dict with challenge and payload

# Verify credential
is_valid, credential, error = verify_credential(
    auth_header="Payment eyJ...",
    secret_key="your_mpp_secret_key",
    expected_realm="video-gen-api"
)

if not is_valid:
    return f"Verification failed: {error}"

# Verify transfer parameters match challenge
transfer_valid, transfer_error = verify_transfer_parameters(
    credential,
    challenge
)

# Check for replay attacks
used_credentials = set()  # Track used credential IDs
replay_valid, replay_error = check_replay_prevention(
    credential,
    used_credentials
)
```

### 3. `mpp.rpc` - RPC Client Interface

```python
from mpp.rpc import RPCClientInterface, MockRPCClient

# Use mock client for testing
mock_client = MockRPCClient(rpc_url="https://rpc.testnet.tempo.xyz")

# Set test balances
mock_client.set_balance("0xAddress...", 10 ** 18)  # 1 TEMP
mock_client.set_token_balance(
    "0xTokenAddress...",
    "0xUserAddress...",
    100 * 10 ** 6  # 100 pathUSD
)

# Make RPC calls
balance = await mock_client.get_balance("0xAddress...")
chain_id = await mock_client.get_chain_id()
tx_hash = await mock_client.send_raw_transaction(tx_bytes)

# Implement your own client
class MyRPCClient(RPCClientInterface):
    async def call(self, method: str, params: list) -> RPCResponse:
        # Your implementation
        pass
    
    async def get_balance(self, address: str, block: str = "latest") -> int:
        # Your implementation
        pass
    
    # ... implement other methods
```

### 4. `mpp.config` - Configuration

```python
from mpp.config import MPPConfig, get_config

# Create config
config = MPPConfig(
    tempo_rpc_url="https://rpc.testnet.tempo.xyz",
    server_private_key="0x...",  # Server wallet private key
    pathusd_address="0x20c0000000000000000000000000000000000000",
    mpp_secret_key="your_32_byte_secret"
)

# Access properties
print(config.SERVER_ADDRESS)      # Derived from private key
print(config.TEMPO_RPC_URL)       # RPC endpoint
print(config.PATHUSD_ADDRESS)     # Token contract
print(config.CHAIN_ID)            # Chain ID (57059 for testnet)

# Get global config (loads from .env)
config = get_config()
```

## Complete Flow Example

### Server Side (Generating Challenge)

```python
from mpp.config import get_config
from mpp.challenge import create_challenge, format_challenge_header

async def generate_video_endpoint(request):
    # Calculate amount
    amount = calculate_price(request.data)
    
    # Get config
    config = get_config()
    
    # Create challenge
    challenge = create_challenge(
        amount=amount,
        recipient=config.SERVER_ADDRESS,
        realm="video-gen-api",
        secret_key=config.MPP_SECRET_KEY
    )
    
    # Store challenge in session
    session_id = store_session(challenge)
    
    # Return 402 with challenge
    return JSONResponse(
        status_code=402,
        content={"error": "Payment required", "session_id": session_id},
        headers={
            "WWW-Authenticate": format_challenge_header(challenge),
            "Cache-Control": "no-store"
        }
    )
```

### Client Side (Creating Credential)

```python
import json
from mpp.challenge import base64url_encode, jcs_encode, base64url_decode

# Get challenge from 402 response
challenge = parse_www_authenticate_header(response.headers["WWW-Authenticate"])

# Create transfer transaction (using web3.py or similar)
tx_bytes = create_tip20_transfer(
    token_address="0x20c0000000000000000000000000000000000000",
    recipient=challenge_request["recipient"],
    amount=challenge_request["amount"]
)

# Sign transaction
signature = sign_transaction(tx_bytes, client_private_key)

# Create credential
credential = {
    "challenge": challenge,
    "payload": {
        "transaction": {
            "bytes": base64url_encode(tx_bytes),
            "signature": signature
        },
        "transfer": {
            "recipient": challenge_request["recipient"],
            "amount": challenge_request["amount"],
            "currency_address": challenge_request["currency_address"]
        }
    },
    "type": "transaction"
}

# Encode credential
credential_json = jcs_encode(credential)
credential_b64 = base64url_encode(credential_json.encode('utf-8'))

# Retry request with payment
response = requests.post(
    url,
    json=request_data,
    headers={
        "Authorization": f"Payment {credential_b64}",
        "X-Session-ID": session_id
    }
)
```

### Server Side (Verifying Credential)

```python
from mpp.config import get_config
from mpp.credential import (
    parse_authorization_header,
    verify_credential,
    verify_transfer_parameters,
)

async def generate_video_with_payment(request):
    auth_header = request.headers.get("Authorization", "")
    session_id = request.headers.get("X-Session-ID")
    
    # Parse credential
    credential_data = parse_authorization_header(auth_header)
    if not credential_data:
        return JSONResponse(status_code=402, content={"error": "Invalid credential"})
    
    # Get stored challenge
    challenge = get_session_challenge(session_id)
    
    # Verify credential
    config = get_config()
    is_valid, credential, error = verify_credential(
        auth_header=auth_header,
        secret_key=config.MPP_SECRET_KEY,
        expected_realm="video-gen-api"
    )
    
    if not is_valid:
        return JSONResponse(status_code=401, content={"error": error})
    
    # Verify transfer parameters
    transfer_valid, transfer_error = verify_transfer_parameters(
        credential,
        challenge
    )
    
    if not transfer_valid:
        return JSONResponse(status_code=402, content={"error": transfer_error})
    
    # Check replay prevention
    credential_id = credential.get('id')
    if credential_id in used_credentials:
        return JSONResponse(status_code=401, content={"error": "Credential already used"})
    
    used_credentials.add(credential_id)
    
    # Payment verified - proceed with business logic
    result = perform_service()
    
    return JSONResponse(content={"success": True, "result": result})
```

## Testing

```python
# Run MPP module tests
pytest test_mpp.py -v

# Run API integration tests
pytest test_main.py -v

# Run all tests
pytest test_mpp.py test_main.py -v
```

## Security Best Practices

1. **Generate Secure Secret Key**:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. **Never Commit Secrets**:
   - Add `.env` to `.gitignore`
   - Use `.env.example` with placeholders

3. **Rotate Keys Periodically**:
   - Change MPP_SECRET_KEY every 90 days
   - Rotate server wallet keys for production

4. **Monitor for Attacks**:
   - Log failed verification attempts
   - Alert on multiple replay attempts
   - Monitor credential usage patterns

5. **Use HTTPS**:
   - Always serve API over HTTPS
   - Never transmit credentials over HTTP

## Error Handling

All verification functions return tuples of `(success, data, error)`:

```python
is_valid, credential, error = verify_credential(...)
if not is_valid:
    logger.warning(f"Verification failed: {error}")
    # Return appropriate HTTP error
```

Common errors:
- "Invalid authorization header format"
- "Challenge HMAC binding verification failed"
- "Challenge has expired"
- "Realm mismatch"
- "Amount insufficient"
- "Recipient mismatch"
- "Credential already used (replay attempt)"

## Support

For issues or questions:
- Check `docs/mpp-implementation-plan.md`
- Review `PHASE1_FIXES.md` for recent changes
- Run tests to verify installation
