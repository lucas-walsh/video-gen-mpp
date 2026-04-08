SPEC: Tempo + MPP Payment Flow (Direct On-Chain)
🧠 Summary

This system implements a Machine Payments Protocol (MPP) flow over HTTP, where:

The server acts as a paid API
The client pays per request using a Tempo-compatible wallet
Payment negotiation happens using HTTP 402 + MPP headers
Payment proof is delivered via Authorization: Payment

MPP defines:

how payment is requested (402 + WWW-Authenticate)
how payment is provided (Authorization: Payment)
how clients retry requests with proof
🧠 High-Level Flow
1. Client → POST /generate
2. Server → 402 Payment Required + WWW-Authenticate: Payment
3. Client → sends on-chain payment (Tempo)
4. Client → retries request with Authorization: Payment <credential>
5. Server → verifies payment via RPC
6. Server → returns video result
⚙️ Protocol-Level Behavior (MPP)
1. Payment Challenge

Server MUST respond:

HTTP/1.1 402 Payment Required
WWW-Authenticate: Payment ...

This header tells the client:

amount
recipient
payment method
2. Payment Submission

Client MUST retry with:

Authorization: Payment <credential>

This follows the same pattern as HTTP auth schemes (like Bearer tokens), where headers signal how to authenticate requests

🧩 Payment Credential Format (Tempo version)

For this implementation, the credential is:

{
  "tx_hash": "0xabc...",
  "chain_id": "tempo-testnet"
}

Encoded as:

Authorization: Payment eyJ0eF9oYXNoIjoiMHhhYmMuLi4ifQ==

(Base64 JSON)

🖥️ SERVER SPEC (Starlette)
Responsibilities

The server MUST:

Return a 402 payment challenge
Parse Authorization: Payment
Verify transaction via RPC
Prevent replay attacks
Execute request after verification
Example Implementation
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.requests import Request
from web3 import Web3
import base64
import json

RPC_URL = "https://your-tempo-rpc"
YOUR_WALLET = "0xYourAddress"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

USED_TXS = set()

app = Starlette()
Payment Challenge (402)
def payment_required(price):
    return JSONResponse(
        {
            "amount": price,
            "currency": "USDC",
            "recipient": YOUR_WALLET,
            "chain_id": "tempo-testnet"
        },
        status_code=402,
        headers={
            "WWW-Authenticate": 'Payment realm="video-api"'
        }
    )
Credential Parsing
def parse_payment_header(header: str):
    if not header.startswith("Payment "):
        return None

    encoded = header.split(" ")[1]
    decoded = base64.b64decode(encoded).decode()

    return json.loads(decoded)
Transaction Verification
def verify_payment(tx_hash, expected_amount):
    if tx_hash in USED_TXS:
        return False

    tx = w3.eth.get_transaction(tx_hash)

    # verify recipient
    if tx["to"].lower() != YOUR_WALLET.lower():
        return False

    value = w3.from_wei(tx["value"], "ether")

    if value < expected_amount:
        return False

    USED_TXS.add(tx_hash)
    return True
Main Endpoint
@app.route("/generate", methods=["POST"])
async def generate(request: Request):
    body = await request.json()
    prompt = body["prompt"]

    price = 0.001  # example

    auth = request.headers.get("Authorization")

    # Step 1: no payment → challenge
    if not auth:
        return payment_required(price)

    # Step 2: parse credential
    credential = parse_payment_header(auth)
    if not credential:
        return JSONResponse({"error": "invalid payment header"}, status_code=400)

    tx_hash = credential["tx_hash"]

    # Step 3: verify payment
    if not verify_payment(tx_hash, price):
        return JSONResponse({"error": "invalid payment"}, status_code=403)

    # Step 4: execute business logic
    return JSONResponse({
        "video_url": "https://example.com/video.mp4"
    })
🧑‍💻 CLIENT SPEC (Python Script)
Responsibilities

The client MUST:

Call API
Detect 402 Payment Required
Extract payment details
Send Tempo transaction
Retry with Authorization: Payment
Example Implementation
from web3 import Web3
import requests
import base64
import json
import os

RPC_URL = "https://your-tempo-rpc"
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

w3 = Web3(Web3.HTTPProvider(RPC_URL))
account = w3.eth.account.from_key(PRIVATE_KEY)

SERVER_URL = "http://localhost:8000/generate"
Send Payment
def send_payment(to, amount):
    tx = {
        "to": to,
        "value": w3.to_wei(amount, "ether"),
        "gas": 21000,
        "nonce": w3.eth.get_transaction_count(account.address),
    }

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)

    return tx_hash.hex()
Build Payment Credential
def build_payment_header(tx_hash):
    payload = {
        "tx_hash": tx_hash,
        "chain_id": "tempo-testnet"
    }

    encoded = base64.b64encode(json.dumps(payload).encode()).decode()

    return f"Payment {encoded}"
Main Flow
def request_video(prompt):
    res = requests.post(SERVER_URL, json={"prompt": prompt})

    if res.status_code != 402:
        return res.json()

    payment_info = res.json()

    tx_hash = send_payment(
        payment_info["recipient"],
        payment_info["amount"]
    )

    header = build_payment_header(tx_hash)

    res2 = requests.post(
        SERVER_URL,
        json={"prompt": prompt},
        headers={"Authorization": header}
    )

    return res2.json()


if __name__ == "__main__":
    print(request_video("dog surfing"))
🧠 Key Design Notes
1. Why Authorization: Payment matters
Standardized across MPP
Enables interoperability
Same pattern as Bearer auth
Required for spec compliance
2. Why NOT use X-TX-HASH
Not portable
Not spec-compliant
Breaks future SDK compatibility
3. Why no vouchers (yet)

This implementation uses:

direct settlement (1 request = 1 tx)

You are NOT using:

sessions
escrow
vouchers
4. RPC Role
Used for:
sending transactions (client)
verifying transactions (server)
5. Gas
Paid by client
covers transaction execution
independent of your pricing
🚀 Future Extensions

After this works, next steps:

1. Switch to USDC (ERC20)
decode transfer logs
verify token contract
2. Add confirmations
wait for block inclusion
3. Add database
prevent replay attacks robustly
4. Move to sessions + vouchers
for streaming payments
🧠 Final Mental Model
