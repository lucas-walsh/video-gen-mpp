#!/usr/bin/env python3
"""
MPP Client Payment Script

Makes payments using the MPP protocol:
1. Makes initial request to /api/video/generate
2. Receives 402 challenge
3. Decodes challenge (parse WWW-Authenticate header, base64url decode request)
4. Extracts: amount, currency, recipient, expires
5. Creates TIP-20 transfer transaction
6. Signs transaction locally (domain 0x76)
7. Creates credential with full challenge echo
8. Retries request with Authorization header
9. Prints results (job_id, status, etc.)
"""

import argparse
import json
import base64
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak
import httpx

from mpp.challenge import (
    base64url_decode,
    base64url_encode,
    jcs_encode,
    parse_challenge_header,
    decode_challenge_request,
)
from mpp.credential import create_credential


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


PATHUSD_ADDRESS = "0x20c0000000000000000000000000000000000000"


def encode_transfer_calldata(recipient: str, amount: str) -> str:
    """
    Encode transfer(address,uint256) function call for TIP-20.
    
    Args:
        recipient: Recipient address (hex string)
        amount: Amount in micro USD (as string)
        
    Returns:
        Hex-encoded calldata (without 0x prefix)
    """
    function_selector = keccak(
        b"transfer(address,uint256)"
    ).hex()[:8]
    
    if recipient.startswith("0x"):
        recipient = recipient[2:]
    recipient_padded = recipient.zfill(64)
    
    amount_int = int(amount)
    amount_padded = hex(amount_int)[2:].zfill(64)
    
    return function_selector + recipient_padded + amount_padded


def create_tempo_transaction(
    recipient: str,
    amount: str,
    sender_address: str,
    nonce: int = 0,
    chain_id: int = 57059,
    valid_before: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Create a Tempo transaction structure for TIP-20 transfer.
    
    Args:
        recipient: Payment recipient address
        amount: Amount in micro USD
        sender_address: Sender (fee payer) address
        nonce: Transaction nonce
        chain_id: Chain ID (default: 57059 for Tempo testnet)
        valid_before: Optional validity timestamp
        
    Returns:
        Transaction dictionary ready for signing
    """
    if valid_before is None:
        valid_before = int(datetime.now(timezone.utc).timestamp()) + 3600
    
    transfer_calldata = encode_transfer_calldata(recipient, amount)
    
    transaction = {
        "type": "0x76",
        "chainId": chain_id,
        "nonce": nonce,
        "to": PATHUSD_ADDRESS,
        "value": "0x0",
        "data": "0x" + transfer_calldata,
        "validBefore": valid_before,
        "feeToken": PATHUSD_ADDRESS,
        "feePayer": sender_address,
        "feePayerSignature": "0x",
    }
    
    return transaction


def encode_transaction_for_signing(transaction: Dict[str, Any]) -> bytes:
    """
    Encode transaction for signing following Tempo spec.
    
    Args:
        transaction: Transaction dictionary
        
    Returns:
        Bytes to sign
    """
    fields = [
        transaction.get("chainId", 0),
        int(transaction.get("nonce", 0)),
        transaction.get("validBefore", 0),
        transaction.get("to", "").lower().replace("0x", "").zfill(40),
        int(transaction.get("value", "0x0"), 16),
        transaction.get("data", "0x")[2:],
        transaction.get("feeToken", "").lower().replace("0x", "").zfill(40),
        transaction.get("feePayer", "").lower().replace("0x", "").zfill(40),
    ]
    
    encoded_parts = []
    for field in fields:
        if isinstance(field, int):
            encoded_parts.append(hex(field)[2:].zfill(64))
        elif isinstance(field, str):
            encoded_parts.append(field.zfill(64))
    
    encoded_string = "".join(encoded_parts)
    return bytes.fromhex(encoded_string)


def sign_transaction(
    transaction: Dict[str, Any],
    private_key: str,
    domain: int = 0x76,
) -> Tuple[str, str]:
    """
    Sign a Tempo transaction locally.
    
    Args:
        transaction: Transaction dictionary
        private_key: Private key (with or without 0x prefix)
        domain: Domain separator (default: 0x76 for user signature)
        
    Returns:
        Tuple of (signature_hex, transaction_hash)
    """
    if private_key.startswith("0x"):
        private_key = private_key[2:]
    
    account = Account.from_key("0x" + private_key)
    sender_address = account.address
    
    transaction_bytes = encode_transaction_for_signing(transaction)
    
    transaction_hash = keccak(transaction_bytes)
    
    signed = account.unsafe_sign_hash(transaction_hash)
    signature = signed.signature.hex()
    
    v = signed.v
    if v == 27:
        recovery_param = 0
    elif v == 28:
        recovery_param = 1
    else:
        recovery_param = v - 27
    
    full_signature = signature + hex(recovery_param)[2:].zfill(2)
    
    tx_hash_input = (
        transaction_bytes + 
        bytes.fromhex(full_signature[2:])
    )
    transaction_hash = "0x" + keccak(tx_hash_input).hex()
    
    return "0x" + full_signature, transaction_hash


def create_signed_transaction_bytes(
    transaction: Dict[str, Any],
    signature: str,
) -> bytes:
    """
    Create full RLP-encoded signed transaction bytes.
    
    Args:
        transaction: Transaction dictionary
        signature: Full signature hex string (with 0x prefix)
        
    Returns:
        RLP-encoded signed transaction bytes
    """
    try:
        from eth_account.typed_transactions import TypedTransaction
        
        tx_dict = {
            "chainId": transaction.get("chainId", 57059),
            "nonce": transaction.get("nonce", 0),
            "to": transaction.get("to", ""),
            "value": int(transaction.get("value", "0x0"), 16),
            "data": transaction.get("data", "0x"),
            "validBefore": transaction.get("validBefore", 0),
            "feeToken": transaction.get("feeToken", ""),
            "feePayer": transaction.get("feePayer", ""),
        }
        
        sig_bytes = bytes.fromhex(signature[2:])
        v = sig_bytes[-1]
        r = int.from_bytes(sig_bytes[:32], 'big')
        s = int.from_bytes(sig_bytes[32:64], 'big')
        
        tx_dict["v"] = v + 27
        tx_dict["r"] = r
        tx_dict["s"] = s
        
        typed_tx = TypedTransaction.from_dict(tx_dict)
        return typed_tx.as_bytes()
        
    except Exception as e:
        logging.error(f"Failed to create signed transaction bytes: {e}")
        return b""


def make_initial_request(
    api_url: str,
    prompt: str,
    duration: int,
    model: str = "fal-ai/veo3.1/fast",
) -> Tuple[Optional[Dict[str, Any]], Optional[str], str, Optional[str]]:
    """
    Make initial request to video generation endpoint.
    
    Args:
        api_url: API base URL
        prompt: Video generation prompt
        duration: Duration in seconds
        model: Video model to use
        
    Returns:
        Tuple of (challenge_dict, www_auth_header, error_message, session_id)
    """
    endpoint = f"{api_url}/api/video/generate"
    
    payload = {
        "prompt": prompt,
        "duration_seconds": duration,
        "model": model,
    }
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=payload)
            
            if response.status_code == 402:
                www_auth = response.headers.get("WWW-Authenticate", "")
                session_id = None
                try:
                    resp_json = response.json()
                    session_id = resp_json.get("session_id")
                except Exception:
                    pass
                if www_auth.startswith("Payment "):
                    challenge = parse_challenge_header(www_auth)
                    if challenge:
                        return challenge, www_auth, "", session_id
                return None, www_auth, "Failed to parse challenge header", session_id
            
            elif response.status_code == 200:
                return None, "", f"Unexpected 200 response: {response.json()}", None
            
            elif response.status_code == 400:
                return None, "", f"Bad request: {response.json()}", None
            
            elif response.status_code == 503:
                return None, "", f"Service unavailable: {response.json()}", None
            
            else:
                return None, "", f"Unexpected status {response.status_code}: {response.text}", None
                
    except httpx.RequestError as e:
        return None, "", f"Request failed: {str(e)}", None


def send_payment_request(
    api_url: str,
    prompt: str,
    duration: int,
    model: str,
    credential_b64: str,
    session_id: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Send request with payment credential.
    
    Args:
        api_url: API base URL
        prompt: Video generation prompt
        duration: Duration in seconds
        model: Video model
        credential_b64: Base64url-encoded credential
        session_id: Session ID from challenge
        
    Returns:
        Tuple of (response_json, error_message)
    """
    endpoint = f"{api_url}/api/video/generate"
    
    payload = {
        "prompt": prompt,
        "duration_seconds": duration,
        "model": model,
    }
    
    headers = {
        "Authorization": f"Payment {credential_b64}",
        "X-Session-ID": session_id,
    }
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            
            if response.status_code == 200:
                return response.json(), ""
            
            elif response.status_code == 401:
                return None, f"Unauthorized: {response.json()}"
            
            elif response.status_code == 402:
                return None, f"Payment failed: {response.json()}"
            
            elif response.status_code == 400:
                return None, f"Bad request: {response.json()}"
            
            elif response.status_code == 503:
                return None, f"Service unavailable: {response.json()}"
            
            else:
                return None, f"Unexpected status {response.status_code}: {response.text}"
                
    except httpx.RequestError as e:
        return None, f"Request failed: {str(e)}"


def run_payment_flow(
    api_url: str,
    prompt: str,
    duration: int,
    private_key: str,
    model: str = "fal-ai/veo3.1/fast",
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Run the complete MPP payment flow.
    
    Args:
        api_url: API base URL
        prompt: Video generation prompt
        duration: Duration in seconds
        private_key: Client private key
        model: Video model
        verbose: Enable verbose logging
        
    Returns:
        Result dictionary with job_id, status, etc.
    """
    result = {
        "success": False,
        "job_id": None,
        "status": None,
        "cost": None,
        "transaction_hash": None,
        "error": None,
    }
    
    print(f"\n{'='*60}")
    print("MPP Client Payment Flow")
    print(f"{'='*60}\n")
    
    print(f"Step 1: Requesting video generation...")
    print(f"  API URL: {api_url}")
    print(f"  Model: {model}")
    print(f"  Duration: {duration}s")
    print(f"  Prompt: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")
    
    challenge, www_auth, error, session_id = make_initial_request(
        api_url, prompt, duration, model
    )
    
    if error:
        print(f"  ✗ Error: {error}")
        result["error"] = error
        return result
    
    if not challenge:
        print(f"  ✗ Failed to receive challenge")
        result["error"] = "No challenge received"
        return result
    
    print(f"\nStep 2: Got 402 challenge")
    print(f"  Challenge ID: {challenge.get('id', 'N/A')[:16]}...")
    if session_id:
        print(f"  Session ID: {session_id}")
    
    request_params = decode_challenge_request(challenge)
    if not request_params:
        print(f"  ✗ Failed to decode challenge request")
        result["error"] = "Failed to decode challenge request"
        return result
    
    amount_usd = request_params.get("amount", "0")
    currency = request_params.get("currency", "pathUSD")
    recipient = request_params.get("recipient", "N/A")
    expires = challenge.get("expires", "N/A")
    
    amount_micro_usd = str(int(float(amount_usd) * 1_000_000))
    
    print(f"  Amount: ${float(amount_usd):.2f} {currency}")
    print(f"  Recipient: {recipient}")
    print(f"  Expires: {expires}")
    
    if not session_id:
        session_id = f"quote_{challenge['id'][:12]}"
    
    print(f"\nStep 3: Creating TIP-20 transfer transaction...")
    
    if private_key.startswith("0x"):
        private_key = private_key[2:]
    account = Account.from_key("0x" + private_key)
    sender_address = account.address
    
    nonce = 0
    
    transaction = create_tempo_transaction(
        recipient=recipient,
        amount=amount_micro_usd,
        sender_address=sender_address,
        nonce=nonce,
        chain_id=57059,
    )
    
    print(f"  To: {transaction['to']}")
    print(f"  From: {sender_address}")
    print(f"  Amount: {amount_micro_usd} (micro USD)")
    print(f"  Nonce: {nonce}")
    print(f"  Type: {transaction['type']}")
    
    if verbose:
        print(f"  Transaction JSON: {json.dumps(transaction, indent=2)}")
    
    print(f"\nStep 4: Signing transaction locally...")
    print(f"  Domain: 0x76 (user signature)")
    print(f"  Note: Transaction signed but NOT broadcast")
    
    signature, tx_hash = sign_transaction(transaction, private_key, domain=0x76)
    
    print(f"  Signature: {signature[:20]}...{signature[-10:]}")
    print(f"  Transaction Hash: {tx_hash}")
    
    print(f"\nStep 5: Creating payment credential...")
    
    signed_tx_bytes = create_signed_transaction_bytes(transaction, signature)
    
    transfer_params = {
        "recipient": recipient,
        "amount": amount_micro_usd,
        "currency": currency,
    }
    
    credential_b64 = create_credential(
        challenge=challenge,
        transaction_hash=tx_hash,
        transfer_params=transfer_params,
        transaction_bytes=signed_tx_bytes if signed_tx_bytes else None,
    )
    
    if not signed_tx_bytes:
        print(f"  Warning: Could not create signed transaction bytes (using mock mode)")
    
    if not signed_tx_bytes:
        print(f"  Warning: Could not create signed transaction bytes (using mock mode)")
    
    print(f"  Credential encoded: {credential_b64[:40]}...")
    
    print(f"\nStep 6: Sending credential to server...")
    
    response_data, error = send_payment_request(
        api_url=api_url,
        prompt=prompt,
        duration=duration,
        model=model,
        credential_b64=credential_b64,
        session_id=session_id or f"quote_{challenge['id'][:12]}",
    )
    
    if error:
        print(f"  ✗ Error: {error}")
        result["error"] = error
        return result
    
    print(f"\nStep 7: Got response: 200 OK")
    print(f"  Job ID: {response_data.get('job_id', 'N/A')}")
    print(f"  Status: {response_data.get('status', 'N/A')}")
    print(f"  Cost: ${float(response_data.get('cost_usd', 0)):.2f}")
    
    result["success"] = True
    result["job_id"] = response_data.get("job_id")
    result["status"] = response_data.get("status")
    result["cost"] = response_data.get("cost_usd")
    result["transaction_hash"] = tx_hash
    result["response"] = response_data
    
    print(f"\n{'='*60}")
    print("Payment flow completed successfully!")
    print(f"{'='*60}\n")
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="MPP Client Payment Script for Video Generation API"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        required=True,
        help="Video generation prompt"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=5,
        help="Video duration in seconds (default: 5)"
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="fal-ai/veo3.1/fast",
        help="Video model (default: fal-ai/veo3.1/fast)"
    )
    parser.add_argument(
        "--private-key",
        type=str,
        default=None,
        help="Client private key (or set CLIENT_PRIVATE_KEY env var)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    private_key = args.private_key
    if not private_key:
        import os
        private_key = os.getenv("CLIENT_PRIVATE_KEY")
    
    if not private_key:
        print("Error: CLIENT_PRIVATE_KEY environment variable not set")
        print("Please set it or use --private-key argument")
        print("\nUsage:")
        print("  export CLIENT_PRIVATE_KEY='0x...'")
        print("  python client-pay.py --prompt 'A cat playing piano'")
        return 1
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    result = run_payment_flow(
        api_url=args.url,
        prompt=args.prompt,
        duration=args.duration,
        private_key=private_key,
        model=args.model,
        verbose=args.verbose,
    )
    
    if result["success"]:
        return 0
    else:
        print(f"\nPayment flow failed: {result['error']}")
        return 1


if __name__ == "__main__":
    exit(main())
