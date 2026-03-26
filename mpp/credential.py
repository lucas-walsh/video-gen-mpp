"""
MPP Credential Verification Module

Parses and verifies payment credentials following the official MPP specification.
Implements challenge echo verification, HMAC binding, transaction signature verification,
transfer parameter verification, and replay prevention.
"""

import json
import base64
import hmac
import hashlib
from typing import Dict, Any, Optional, Tuple, Set
from datetime import datetime, timezone

from . import challenge as mpp_challenge


def base64url_encode(data: bytes) -> str:
    """Encode bytes to base64url without padding."""
    encoded = base64.urlsafe_b64encode(data).decode('ascii')
    return encoded.rstrip('=')


def base64url_decode(data: str) -> bytes:
    """Decode base64url string with or without padding."""
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


def parse_authorization_header(
    auth_header: str
) -> Optional[Dict[str, Any]]:
    """
    Parse Authorization: Payment header and decode credential.
    
    Args:
        auth_header: Authorization header value
        
    Returns:
        Decoded credential dictionary or None if parsing fails
    """
    if not auth_header:
        return None
    
    if not auth_header.startswith('Payment '):
        return None
    
    try:
        credential_b64 = auth_header[8:].strip()
        if not credential_b64:
            return None
        
        credential_json = base64url_decode(credential_b64).decode('utf-8')
        return json.loads(credential_json)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def extract_challenge_from_credential(
    credential: Dict[str, Any]
) -> Optional[Dict[str, str]]:
    """
    Extract the echoed challenge from a credential.
    
    Args:
        credential: Decoded credential dictionary
        
    Returns:
        Challenge dictionary or None if not found
    """
    challenge = credential.get('challenge')
    if not challenge or not isinstance(challenge, dict):
        return None
    
    required_fields = ['id', 'realm', 'method', 'intent', 'request', 'expires']
    for field in required_fields:
        if field not in challenge:
            return None
    
    return challenge


def verify_credential(
    auth_header: str,
    secret_key: str,
    expected_realm: Optional[str] = None,
    used_credentials: Optional[Set[str]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verify a payment credential.
    
    Args:
        auth_header: Authorization header value
        secret_key: Secret key for HMAC verification
        expected_realm: Expected realm value (optional)
        used_credentials: Set of already-used credential IDs for replay prevention
        
    Returns:
        Tuple of (is_valid, decoded_credential, error_message)
    """
    credential = parse_authorization_header(auth_header)
    if not credential:
        return False, None, "Invalid authorization header format"
    
    challenge = extract_challenge_from_credential(credential)
    if not challenge:
        return False, None, "Missing or invalid challenge in credential"
    
    if expected_realm and challenge.get('realm') != expected_realm:
        return False, None, f"Realm mismatch: expected {expected_realm}"
    
    if not mpp_challenge.verify_challenge_binding(challenge, secret_key):
        return False, None, "Challenge HMAC binding verification failed"
    
    if mpp_challenge.is_challenge_expired(challenge):
        return False, None, "Challenge has expired"
    
    request_params = mpp_challenge.decode_challenge_request(challenge)
    if not request_params:
        return False, None, "Failed to decode challenge request"
    
    if used_credentials is None:
        used_credentials = set()
    
    replay_valid, replay_error = check_replay_prevention(credential, used_credentials)
    if not replay_valid:
        return False, None, replay_error
    
    return True, credential, ""


def extract_transfer_params(
    credential: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Extract transfer parameters from credential payload.
    
    Args:
        credential: Decoded credential dictionary
        
    Returns:
        Transfer parameters dictionary or None if not found
    """
    payload = credential.get('payload', {})
    if not payload or not isinstance(payload, dict):
        return None
    
    transfer = payload.get('transfer')
    if not transfer or not isinstance(transfer, dict):
        return None
    
    return transfer


def verify_transfer_parameters(
    credential: Dict[str, Any],
    challenge: Dict[str, str],
) -> Tuple[bool, str]:
    """
    Verify that transfer parameters match the challenge.
    
    Args:
        credential: Decoded credential dictionary
        challenge: Extracted challenge dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    transfer = extract_transfer_params(credential)
    if not transfer:
        return False, "Missing transfer parameters in credential"
    
    request_params = mpp_challenge.decode_challenge_request(challenge)
    if not request_params:
        return False, "Failed to decode challenge request"
    
    expected_recipient = request_params.get('recipient', '').lower()
    actual_recipient = transfer.get('recipient', '').lower()
    
    if expected_recipient and actual_recipient != expected_recipient:
        return False, f"Recipient mismatch: expected {expected_recipient}, got {actual_recipient}"
    
    expected_amount = float(request_params.get('amount', '0'))
    actual_amount = float(transfer.get('amount', '0'))
    
    if actual_amount < expected_amount:
        return False, f"Amount insufficient: expected >= {expected_amount}, got {actual_amount}"
    
    expected_currency = request_params.get('currency', 'pathUSD')
    actual_currency = transfer.get('currency', 'pathUSD')
    
    if actual_currency != expected_currency:
        return False, f"Currency mismatch: expected {expected_currency}, got {actual_currency}"
    
    return True, ""


def check_replay_prevention(
    credential: Dict[str, Any],
    used_credentials: Set[str],
) -> Tuple[bool, str]:
    """
    Check replay prevention using credential ID tracking.
    
    Uses challenge ID as the unique identifier for replay prevention.
    
    Args:
        credential: Decoded credential dictionary
        used_credentials: Set of already-used credential IDs
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    challenge = credential.get('challenge', {})
    credential_id = challenge.get('id') or credential.get('id')
    
    if credential_id:
        if credential_id in used_credentials:
            return False, "Credential already used (replay attempt)"
    
    payload = credential.get('payload', {})
    valid_before = payload.get('validBefore')
    
    if valid_before:
        try:
            valid_before_dt = datetime.fromisoformat(valid_before)
            now = datetime.now(timezone.utc)
            if now >= valid_before_dt:
                return False, "Credential validity period expired (validBefore)"
        except (ValueError, TypeError):
            pass
    
    return True, ""


def create_credential(
    challenge: Dict[str, Any],
    transaction_hash: str,
    transfer_params: Dict[str, Any],
    valid_before: Optional[datetime] = None,
) -> str:
    """
    Create a payment credential for client use.
    
    Args:
        challenge: Challenge dictionary
        transaction_hash: Transaction hash
        transfer_params: Transfer parameters (recipient, amount, currency)
        valid_before: Optional validity deadline
        
    Returns:
        Base64url-encoded credential string
    """
    credential = {
        'challenge': challenge,
        'type': 'transaction',
        'payload': {
            'transaction_hash': transaction_hash,
            'transfer': transfer_params,
        }
    }
    
    if valid_before:
        credential['payload']['validBefore'] = valid_before.isoformat()
    
    credential_json = json.dumps(credential, sort_keys=True, separators=(',', ':'))
    return base64url_encode(credential_json.encode('utf-8'))


def recover_signer_from_transaction(tx_bytes: bytes) -> Optional[str]:
    """
    Recover signer address from signed transaction bytes.
    
    Uses secp256k1 signature recovery with domain 0x76 (Tempo).
    
    Args:
        tx_bytes: Raw signed transaction bytes (hex or raw)
        
    Returns:
        Recovered signer address or None if recovery fails
    """
    try:
        if isinstance(tx_bytes, str):
            if tx_bytes.startswith('0x'):
                tx_bytes = bytes.fromhex(tx_bytes[2:])
            else:
                tx_bytes = bytes.fromhex(tx_bytes)
        
        try:
            import eth_keys
            from eth_utils import keccak, to_checksum_address
            from eth_account._utils.typed_transactions import TypedTransaction
            
            typed_tx = TypedTransaction.from_bytes(tx_bytes)
            signature = typed_tx.signature
            v = signature.v
            r = signature.r
            s = signature.s
            
            signature_obj = eth_keys.keys.Signature(vrs=(v - 27, r, s))
            
            if hasattr(typed_tx, 'envelope_bytes'):
                msg_bytes = typed_tx.envelope_bytes[:-65]
            else:
                msg_bytes = tx_bytes[:-65]
            
            public_key = signature_obj.recover_public_key_from_msg(msg_bytes)
            
            addr_bytes = keccak(public_key.to_bytes()[1:])[12:]
            address = to_checksum_address(addr_bytes)
            
            return address
            
        except ImportError:
            return None
        except Exception:
            return None
                
    except Exception:
        return None


def verify_transaction_signature(
    tx_bytes: bytes,
    expected_signer: Optional[str] = None,
) -> Tuple[bool, Optional[str], str]:
    """
    Verify secp256k1 signature from transaction bytes.
    
    Recovers signer from signature and optionally verifies against expected address.
    Domain 0x76 (Tempo) is used for signature verification.
    
    Args:
        tx_bytes: Signed transaction bytes
        expected_signer: Optional expected signer address
        
    Returns:
        Tuple of (is_valid, recovered_signer, error_message)
    """
    if not tx_bytes:
        return False, None, "Empty transaction bytes"
    
    recovered = recover_signer_from_transaction(tx_bytes)
    
    if not recovered:
        return False, None, "Failed to recover signer from transaction"
    
    if expected_signer:
        if recovered.lower() != expected_signer.lower():
            return False, recovered, f"Signer mismatch: expected {expected_signer}, got {recovered}"
    
    return True, recovered, ""


def decode_transfer_calldata(calldata: str) -> Optional[Dict[str, Any]]:
    """
    Decode ERC20 transfer() calldata to extract recipient and amount.
    
    transfer(address,uint256) selector: 0xa9059cbb
    Args:
        - address: 20 bytes (padded to 32)
        - uint256: 32 bytes
        
    Args:
        calldata: Hex-encoded calldata string
        
    Returns:
        Dictionary with recipient and amount, or None if decoding fails
    """
    try:
        if not calldata:
            return None
        
        if isinstance(calldata, str) and calldata.startswith('0x'):
            calldata = calldata[2:]
        
        calldata_bytes = bytes.fromhex(calldata)
        
        if len(calldata_bytes) < 4:
            return None
        
        selector = calldata_bytes[:4].hex()
        
        if selector != 'a9059cbb':
            return None
        
        if len(calldata_bytes) < 68:
            return None
        
        recipient_bytes = calldata_bytes[4:36]
        amount_bytes = calldata_bytes[36:68]
        
        recipient_int = int.from_bytes(recipient_bytes, 'big')
        recipient = '0x' + format(recipient_int & ((1 << 160) - 1), '040x')
        
        amount = int.from_bytes(amount_bytes, 'big')
        
        return {
            'recipient': recipient,
            'amount': str(amount),
            'method': 'transfer'
        }
        
    except (ValueError, IndexError):
        return None


def verify_transfer_calldata(
    tx_bytes: bytes,
    expected_recipient: str,
    expected_amount: int,
    currency_address: Optional[str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verify transaction calldata contains correct transfer parameters.
    
    Args:
        tx_bytes: Signed transaction bytes
        expected_recipient: Expected recipient address
        expected_amount: Expected minimum amount (in token smallest units)
        currency_address: Expected token contract address
        
    Returns:
        Tuple of (is_valid, decoded_calldata, error_message)
    """
    try:
        if isinstance(tx_bytes, str):
            if tx_bytes.startswith('0x'):
                tx_bytes = bytes.fromhex(tx_bytes[2:])
            else:
                tx_bytes = bytes.fromhex(tx_bytes)
        
        try:
            from eth_account._utils.typed_transactions import TypedTransaction
            typed_tx = TypedTransaction.from_bytes(tx_bytes)
            calldata = typed_tx.transaction.data.hex() if typed_tx.transaction.data else ''
            to_address = typed_tx.transaction.to
            
        except Exception:
            to_address = b''
            calldata = ''
        
        if isinstance(to_address, bytes):
            if len(to_address) == 20:
                to_address = '0x' + to_address.hex()
            elif len(to_address) == 0:
                to_address = None
            else:
                to_address = '0x' + to_address.hex()
        
        if currency_address and to_address:
            if to_address.lower() != currency_address.lower():
                return False, None, f"Token address mismatch: expected {currency_address}, got {to_address}"
        
        if not calldata:
            return False, None, "No calldata in transaction"
        
        decoded = decode_transfer_calldata('0x' + calldata)
        
        if not decoded:
            return False, None, "Failed to decode transfer calldata"
        
        actual_recipient = decoded['recipient'].lower()
        expected_recipient_normalized = expected_recipient.lower()
        
        if actual_recipient != expected_recipient_normalized:
            return False, decoded, f"Recipient mismatch: expected {expected_recipient}, got {decoded['recipient']}"
        
        actual_amount = int(decoded['amount'])
        
        if actual_amount < expected_amount:
            return False, decoded, f"Amount insufficient: expected >= {expected_amount}, got {actual_amount}"
        
        return True, decoded, ""
        
    except Exception as e:
        return False, None, f"Calldata verification failed: {str(e)}"


def extract_transaction_hash(credential: Dict[str, Any]) -> Optional[str]:
    """
    Extract transaction hash from credential payload.
    
    Args:
        credential: Decoded credential dictionary
        
    Returns:
        Transaction hash or None if not found
    """
    payload = credential.get('payload', {})
    if not payload:
        return None
    
    return payload.get('transaction_hash') or payload.get('transactionHash')


def extract_transaction_bytes(credential: Dict[str, Any]) -> Optional[bytes]:
    """
    Extract raw transaction bytes from credential payload.
    
    Args:
        credential: Decoded credential dictionary
        
    Returns:
        Transaction bytes or None if not found
    """
    payload = credential.get('payload', {})
    if not payload:
        return None
    
    tx_bytes = payload.get('transaction_bytes') or payload.get('transactionBytes')
    
    if not tx_bytes:
        return None
    
    if isinstance(tx_bytes, str):
        if tx_bytes.startswith('0x'):
            return bytes.fromhex(tx_bytes[2:])
        return bytes.fromhex(tx_bytes)
    
    if isinstance(tx_bytes, bytes):
        return tx_bytes
    
    return None


def verify_credential_full(
    auth_header: str,
    secret_key: str,
    expected_realm: str,
    used_credentials: Set[str],
    currency_address: str,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Full credential verification including signature and calldata verification.
    
    This is the main entry point for verifying payment credentials.
    
    Args:
        auth_header: Authorization header value
        secret_key: Secret key for HMAC verification
        expected_realm: Expected realm value
        used_credentials: Set of already-used credential IDs
        currency_address: Expected token contract address
        
    Returns:
        Tuple of (is_valid, decoded_credential, error_message)
    """
    is_valid, credential, error = verify_credential(
        auth_header=auth_header,
        secret_key=secret_key,
        expected_realm=expected_realm,
        used_credentials=used_credentials,
    )
    
    if not is_valid:
        return False, None, error
    
    if not credential:
        return False, None, "Credential parsing failed"
    
    challenge = extract_challenge_from_credential(credential)
    if not challenge:
        return False, None, "Missing challenge in credential"
    
    request_params = mpp_challenge.decode_challenge_request(challenge)
    if not request_params:
        return False, None, "Failed to decode challenge request"
    
    transfer_params, transfer_error = verify_transfer_parameters(credential, challenge)
    if not transfer_params:
        return False, None, transfer_error
    
    tx_bytes = extract_transaction_bytes(credential)
    
    if tx_bytes:
        expected_recipient = request_params.get('recipient', '')
        expected_amount = int(float(request_params.get('amount', '0')) * 10 ** 18)
        
        calldata_valid, decoded_calldata, calldata_error = verify_transfer_calldata(
            tx_bytes=tx_bytes,
            expected_recipient=expected_recipient,
            expected_amount=expected_amount,
            currency_address=currency_address,
        )
        
        if not calldata_valid:
            return False, None, f"Transaction calldata verification failed: {calldata_error}"
        
        sig_valid, recovered_signer, sig_error = verify_transaction_signature(tx_bytes)
        
        if not sig_valid:
            return False, None, f"Transaction signature verification failed: {sig_error}"
    
    return True, credential, ""
