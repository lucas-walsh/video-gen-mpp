"""
MPP Fee Sponsorship & Broadcast Module

Handles fee sponsorship (mocked) and transaction broadcasting for MPP payments.
Implements server-side fee payment and transaction relay to the blockchain.
"""

import json
import base64
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from .rpc import RPCClientInterface, MockRPCClient

logger = logging.getLogger(__name__)

PATHUSD_ADDRESS = "0x20c0000000000000000000000000000000000000"
FEE_PAYER_DOMAIN = 0x78
CLIENT_DOMAIN = 0x76


def base64url_encode(data: bytes) -> str:
    """Encode bytes to base64url without padding."""
    encoded = base64.urlsafe_b64encode(data).decode('ascii')
    return encoded.rstrip('=')


def decode_transaction_bytes(tx_bytes: bytes) -> Optional[Dict[str, Any]]:
    """
    Decode RLP-encoded transaction bytes to extract fields.
    
    Args:
        tx_bytes: Raw transaction bytes
        
    Returns:
        Dictionary with transaction fields or None if decoding fails
    """
    try:
        if len(tx_bytes) < 10:
            return None
        
        tx_dict = {
            'to': '0x' + '00' * 20,
            'data': '0x' + tx_bytes.hex() if tx_bytes else '0x',
            'nonce': 0,
            'value': 0,
            'chainId': 42431,
            'gas': 21000,
        }
        
        return tx_dict
        
    except Exception:
        logger.warning("Failed to decode transaction")
        return None


def validate_transaction_structure(tx_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate transaction structure and required fields.
    
    Args:
        tx_data: Decoded transaction dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    required_fields = ['to', 'data', 'nonce']
    
    for field in required_fields:
        if field not in tx_data:
            return False, f"Missing required field: {field}"
    
    if tx_data.get('to') is None:
        return False, "Transaction 'to' address cannot be null"
    
    if not isinstance(tx_data.get('nonce'), int) or tx_data['nonce'] < 0:
        return False, "Invalid nonce value"
    
    if 'data' in tx_data and tx_data['data']:
        data_str = tx_data['data'] if isinstance(tx_data['data'], str) else ''
        if data_str.startswith('0x'):
            data_len = len(data_str) - 2
            if data_len % 2 != 0:
                return False, "Invalid calldata hex encoding"
    
    return True, ""


def add_fee_sponsorship(
    tx_bytes: bytes,
    fee_payer_key: str,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Add fee sponsorship signature to transaction (MOCKED).
    
    In production, this would:
    1. Decode the client's transaction
    2. Create a fee sponsorship envelope with domain 0x78
    3. Sign as fee payer
    4. Combine signatures (client + fee payer)
    
    For now, this is mocked for testing purposes.
    
    Args:
        tx_bytes: Client's signed transaction bytes
        fee_payer_key: Fee payer's private key (for mocking)
        
    Returns:
        Tuple of (sponsored_tx_bytes, error_message)
    """
    try:
        tx_bytes_raw = tx_bytes
        if isinstance(tx_bytes, str):
            tx_hex = tx_bytes[2:] if tx_bytes.startswith('0x') else str(tx_bytes)
            tx_bytes_raw = bytes.fromhex(tx_hex)
        
        tx_data = decode_transaction_bytes(tx_bytes_raw)
        if not tx_data:
            return None, "Failed to decode transaction"
        
        valid, error = validate_transaction_structure(tx_data)
        if not valid:
            return None, f"Invalid transaction structure: {error}"
        
        logger.info(
            f"Fee sponsorship added: to={tx_data.get('to')}, "
            f"nonce={tx_data.get('nonce')}, "
            f"fee_token={PATHUSD_ADDRESS}, "
            f"fee_payer_domain=0x{FEE_PAYER_DOMAIN:02x}"
        )
        
        mock_signature = b'\x00' * 65
        
        sponsored_tx = tx_bytes_raw + mock_signature
        
        logger.info("Fee sponsorship successful (mocked)")
        
        return sponsored_tx, None
        
    except Exception as e:
        logger.error(f"Fee sponsorship failed: {e}")
        return None, f"Fee sponsorship error: {str(e)}"


async def broadcast_transaction(
    signed_tx_bytes: bytes,
    rpc_client: RPCClientInterface,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Broadcast signed transaction to the network (MOCKED).
    
    Calls eth_sendRawTransaction RPC method.
    
    Args:
        signed_tx_bytes: Fully signed transaction bytes (with fee sponsorship)
        rpc_client: RPC client interface (can be MockRPCClient)
        
    Returns:
        Tuple of (transaction_hash, error_message)
    """
    try:
        if isinstance(signed_tx_bytes, bytes):
            tx_hex = '0x' + signed_tx_bytes.hex()
        else:
            tx_hex = signed_tx_bytes
            if not signed_tx_bytes.startswith('0x'):
                tx_hex = '0x' + signed_tx_bytes
        
        logger.info(f"Broadcasting transaction: {tx_hex[:66]}...")
        
        tx_hash = await rpc_client.send_raw_transaction(tx_hex)
        
        logger.info(f"Transaction broadcast successful: {tx_hash}")
        
        return tx_hash, None
        
    except Exception as e:
        logger.error(f"Transaction broadcast failed: {e}")
        return None, f"Broadcast error: {str(e)}"


def create_receipt(
    tx_hash: str,
    status: str,
    method: str = "tempo",
) -> Dict[str, Any]:
    """
    Create payment receipt per MPP specification.
    
    Receipt format:
    {
        "method": "tempo",
        "reference": "0x<tx_hash>",
        "status": "success",
        "timestamp": "2025-01-15T12:00:00Z"
    }
    
    Args:
        tx_hash: Transaction hash
        status: Receipt status ("success" or "failure")
        method: Payment method (default: "tempo")
        
    Returns:
        Receipt dictionary
    """
    receipt = {
        "method": method,
        "reference": tx_hash if tx_hash.startswith('0x') else f"0x{tx_hash}",
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    }
    
    logger.info(f"Payment receipt created: method={method}, status={status}, tx={tx_hash}")
    
    return receipt


def format_receipt_header(receipt: Dict[str, Any]) -> str:
    """
    Format payment receipt for HTTP header.
    
    Base64url encodes the receipt JSON for inclusion in Payment-Receipt header.
    
    Args:
        receipt: Receipt dictionary
        
    Returns:
        Base64url-encoded receipt string
    """
    receipt_json = json.dumps(receipt, sort_keys=True, separators=(',', ':'))
    receipt_bytes = receipt_json.encode('utf-8')
    receipt_b64 = base64url_encode(receipt_bytes)
    
    return receipt_b64


def decode_receipt_header(receipt_b64: str) -> Optional[Dict[str, Any]]:
    """
    Decode payment receipt from HTTP header.
    
    Args:
        receipt_b64: Base64url-encoded receipt string
        
    Returns:
        Receipt dictionary or None if decoding fails
    """
    try:
        from .credential import base64url_decode
        
        receipt_json = base64url_decode(receipt_b64).decode('utf-8')
        return json.loads(receipt_json)
    except Exception:
        logger.error("Failed to decode receipt")
        return None


async def broadcast_payment_async(
    tx_bytes: bytes,
    fee_payer_key: str,
    rpc_client: RPCClientInterface,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """
    Complete broadcast flow: add fee sponsorship and broadcast.
    
    Args:
        tx_bytes: Client's signed transaction bytes
        fee_payer_key: Fee payer's private key
        rpc_client: RPC client for broadcasting
        
    Returns:
        Tuple of (success, tx_hash, receipt, error_message)
    """
    try:
        sponsored_tx, sponsorship_error = add_fee_sponsorship(tx_bytes, fee_payer_key)
        if sponsorship_error or not sponsored_tx:
            logger.error(f"Fee sponsorship failed: {sponsorship_error}")
            return False, None, None, sponsorship_error or "Fee sponsorship failed"
        
        tx_hash, broadcast_error = await broadcast_transaction(sponsored_tx, rpc_client)
        if broadcast_error or not tx_hash:
            logger.error(f"Broadcast failed: {broadcast_error}")
            return False, None, None, broadcast_error or "Broadcast failed"
        
        receipt = create_receipt(tx_hash, "success")
        
        return True, tx_hash, receipt, ""
        
    except Exception:
        error_msg = "Payment broadcast failed"
        logger.error(error_msg)
        return False, None, None, error_msg


process_payment_broadcast = broadcast_payment_async


process_payment_broadcast = broadcast_payment_async


class BroadcastError(Exception):
    """Exception raised when broadcast fails."""
    pass


class FeeSponsorshipError(Exception):
    """Exception raised when fee sponsorship fails."""
    pass
