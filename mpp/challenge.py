"""
MPP Challenge Generation Module

Generates payment challenges following the official MPP specification.
Implements HMAC-SHA256 binding, JCS encoding, and base64url encoding.
"""

import hashlib
import hmac
import json
import base64
import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone


def base64url_encode(data: bytes) -> str:
    """
    Encode bytes to base64url without padding.
    
    Args:
        data: Bytes to encode
        
    Returns:
        Base64url encoded string without padding
    """
    encoded = base64.urlsafe_b64encode(data).decode('ascii')
    return encoded.rstrip('=')


def base64url_decode(data: str) -> bytes:
    """
    Decode base64url string with or without padding.
    
    Args:
        data: Base64url encoded string
        
    Returns:
        Decoded bytes
    """
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


def jcs_encode(obj: Any) -> str:
    """
    JSON Canonicalization Scheme (JCS) encoding.
    
    Produces deterministic JSON output:
    - Keys sorted alphabetically
    - No trailing whitespace
    - UTF-8 encoded
    - Minimal separators
    
    Args:
        obj: Python object to encode (dict, list, etc.)
        
    Returns:
        JCS-encoded JSON string
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False
    )


def jcs_decode(data: str) -> Any:
    """
    Decode JCS-encoded JSON string.
    
    Args:
        data: JCS-encoded JSON string
        
    Returns:
        Decoded Python object
    """
    return json.loads(data)


def create_challenge(
    amount: float,
    recipient: str,
    realm: str,
    method: str = "tempo",
    currency: str = "pathUSD",
    currency_address: str = "0x20c0000000000000000000000000000000000000",
    expires_in: int = 300,
    secret_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create an MPP payment challenge with HMAC binding.
    
    Args:
        amount: Payment amount in currency units
        recipient: Payment recipient address (hex string)
        realm: Realm identifier (e.g., "api.example.com")
        method: Payment method (default: "tempo")
        currency: Currency name (default: "pathUSD")
        currency_address: Token contract address
        expires_in: Challenge validity in seconds (default: 300)
        secret_key: Secret key for HMAC binding
        
    Returns:
        Challenge dictionary with all parameters
    """
    if secret_key is None:
        raise ValueError("secret_key is required for challenge creation")
    
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(
        time.time() + expires_in, tz=timezone.utc
    )
    
    request_params = {
        "amount": f"{amount:.6f}",
        "currency": currency,
        "currency_address": currency_address,
        "method": method,
        "recipient": recipient,
        "realm": realm,
        "timestamp": now.isoformat(),
    }
    
    request_jcs = jcs_encode(request_params)
    request_b64 = base64url_encode(request_jcs.encode('utf-8'))
    
    hmac_input = f"{request_b64}.{secret_key}".encode('utf-8')
    challenge_id = hmac.new(
        secret_key.encode('utf-8'),
        request_jcs.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    challenge = {
        "id": challenge_id,
        "realm": realm,
        "method": method,
        "intent": "charge",
        "request": request_b64,
        "expires": expires_at.isoformat(),
    }
    
    return challenge


def format_challenge_header(challenge: Dict[str, Any]) -> str:
    """
    Format challenge as WWW-Authenticate header value.
    
    Args:
        challenge: Challenge dictionary
        
    Returns:
        Formatted header value string
    """
    parts = [
        f'Payment realm="{challenge["realm"]}"',
        f'id="{challenge["id"]}"',
        f'method="{challenge["method"]}"',
        f'intent="{challenge["intent"]}"',
        f'request="{challenge["request"]}"',
        f'expires="{challenge["expires"]}"',
    ]
    return ', '.join(parts)


def parse_challenge_header(header_value: str) -> Optional[Dict[str, str]]:
    """
    Parse WWW-Authenticate header value into challenge dict.
    
    Args:
        header_value: Header value string
        
    Returns:
        Challenge dictionary or None if parsing fails
    """
    if not header_value.startswith('Payment '):
        return None
    
    params_str = header_value[8:]
    params = {}
    
    current_key = None
    current_value = ""
    in_quotes = False
    
    i = 0
    while i < len(params_str):
        char = params_str[i]
        
        if char == '"' and (i == 0 or params_str[i-1] != '\\'):
            in_quotes = not in_quotes
            i += 1
            continue
        
        if char == '=' and not in_quotes and current_key is None:
            current_key = current_value.strip()
            current_value = ""
            i += 1
            continue
        
        if char == ',' and not in_quotes:
            if current_key:
                params[current_key] = current_value.strip()
            current_key = None
            current_value = ""
            i += 1
            continue
        
        current_value += char
        i += 1
    
    if current_key:
        params[current_key] = current_value.strip()
    
    return params if params else None


def decode_challenge_request(challenge: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Decode and parse the request field from a challenge.
    
    Args:
        challenge: Challenge dictionary with 'request' field
        
    Returns:
        Decoded request parameters or None if decoding fails
    """
    try:
        request_b64 = challenge.get('request', '')
        request_jcs = base64url_decode(request_b64).decode('utf-8')
        return jcs_decode(request_jcs)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def verify_challenge_binding(
    challenge: Dict[str, str],
    secret_key: str
) -> bool:
    """
    Verify that a challenge ID matches the HMAC binding.
    
    Args:
        challenge: Challenge dictionary
        secret_key: Secret key for HMAC verification
        
    Returns:
        True if binding is valid, False otherwise
    """
    try:
        challenge_id = challenge.get('id', '')
        request_b64 = challenge.get('request', '')
        
        request_jcs = base64url_decode(request_b64).decode('utf-8')
        
        expected_id = hmac.new(
            secret_key.encode('utf-8'),
            request_jcs.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(challenge_id, expected_id)
    except Exception:
        return False


def is_challenge_expired(challenge: Dict[str, str]) -> bool:
    """
    Check if a challenge has expired.
    
    Args:
        challenge: Challenge dictionary with 'expires' field
        
    Returns:
        True if expired, False otherwise
    """
    try:
        expires_str = challenge.get('expires', '')
        expires_at = datetime.fromisoformat(expires_str)
        now = datetime.now(timezone.utc)
        return now >= expires_at
    except (ValueError, TypeError):
        return True
