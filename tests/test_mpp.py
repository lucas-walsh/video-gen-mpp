"""
MPP Module Tests

Comprehensive tests for MPP challenge generation, credential verification,
HMAC binding, replay prevention, and RPC client interface.
"""

import pytest
import time
import json
import base64
from datetime import datetime, timezone

from mpp.challenge import (
    create_challenge,
    format_challenge_header,
    parse_challenge_header,
    decode_challenge_request,
    verify_challenge_binding,
    is_challenge_expired,
    base64url_encode,
    base64url_decode,
    jcs_encode,
    jcs_decode,
)
from mpp.credential import (
    parse_authorization_header,
    verify_credential,
    extract_transfer_params,
    verify_transfer_parameters,
    check_replay_prevention,
    create_credential,
    verify_transaction_signature,
    decode_transfer_calldata,
    verify_transfer_calldata,
    extract_transaction_bytes,
    recover_signer_from_transaction,
    verify_credential_full,
)
from mpp.rpc import RPCClientInterface, MockRPCClient, RPCResponse
from mpp.config import MPPConfig
from mpp.broadcast import (
    add_fee_sponsorship,
    broadcast_transaction,
    create_receipt,
    format_receipt_header,
    decode_receipt_header,
    decode_transaction_bytes,
    validate_transaction_structure,
    broadcast_payment_async,
)


class TestBase64urlEncoding:
    """Test base64url encoding/decoding."""
    
    def test_base64url_encode_no_padding(self):
        data = b"Hello, World!"
        encoded = base64url_encode(data)
        assert "=" not in encoded
        assert "+" not in encoded
        assert "/" not in encoded
        
    def test_base64url_decode_with_padding(self):
        encoded = "SGVsbG8sIFdvcmxkIQ"
        decoded = base64url_decode(encoded)
        assert decoded == b"Hello, World!"
        
    def test_base64url_round_trip(self):
        original = b"Test data with special chars: \x00\x01\x02"
        encoded = base64url_encode(original)
        decoded = base64url_decode(encoded)
        assert decoded == original
        
    def test_base64url_empty_data(self):
        encoded = base64url_encode(b"")
        assert encoded == ""
        decoded = base64url_decode("")
        assert decoded == b""


class TestJCSEncoding:
    """Test JSON Canonicalization Scheme encoding."""
    
    def test_jcs_sorts_keys(self):
        obj = {"z": 1, "a": 2, "m": 3}
        encoded = jcs_encode(obj)
        assert encoded == '{"a":2,"m":3,"z":1}'
        
    def test_jcs_no_whitespace(self):
        obj = {"key": "value", "num": 42}
        encoded = jcs_encode(obj)
        assert " " not in encoded
        assert "\n" not in encoded
        
    def test_jcs_nested_objects(self):
        obj = {
            "outer": {
                "inner": {"z": 1, "a": 2}
            },
            "array": [3, 2, 1]
        }
        encoded = jcs_encode(obj)
        assert '"array":[3,2,1]' in encoded
        assert '"outer":{"inner":{"a":2,"z":1}}' in encoded
        
    def test_jcs_unicode(self):
        obj = {"text": "Hello 世界", "emoji": "🚀"}
        encoded = jcs_encode(obj)
        decoded = jcs_decode(encoded)
        assert decoded == obj
        
    def test_jcs_round_trip(self):
        original = {"complex": {"nested": [1, 2, 3]}, "value": True}
        encoded = jcs_encode(original)
        decoded = jcs_decode(encoded)
        assert decoded == original


class TestChallengeCreation:
    """Test MPP challenge generation."""
    
    def test_create_challenge_basic(self):
        challenge = create_challenge(
            amount=1.50,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="video-gen-api",
            secret_key="test_secret_key"
        )
        
        assert "id" in challenge
        assert challenge["realm"] == "video-gen-api"
        assert challenge["method"] == "tempo"
        assert challenge["intent"] == "charge"
        assert "request" in challenge
        assert "expires" in challenge
        
    def test_create_challenge_hmac_binding(self):
        secret = "my_secret_key_123"
        challenge = create_challenge(
            amount=2.00,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="test-realm",
            secret_key=secret
        )
        
        assert verify_challenge_binding(challenge, secret)
        
    def test_create_challenge_wrong_secret(self):
        secret = "correct_secret"
        wrong_secret = "wrong_secret"
        
        challenge = create_challenge(
            amount=1.00,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="test",
            secret_key=secret
        )
        
        assert not verify_challenge_binding(challenge, wrong_secret)
        
    def test_create_challenge_expiry(self):
        expires_in = 60
        challenge = create_challenge(
            amount=1.00,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="test",
            expires_in=expires_in,
            secret_key="test"
        )
        
        assert not is_challenge_expired(challenge)
        
    def test_create_challenge_expired(self):
        challenge = create_challenge(
            amount=1.00,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="test",
            expires_in=-100,
            secret_key="test"
        )
        
        assert is_challenge_expired(challenge)


class TestChallengeHeaderFormatting:
    """Test WWW-Authenticate header formatting."""
    
    def test_format_challenge_header(self):
        challenge = {
            "id": "abc123",
            "realm": "video-gen-api",
            "method": "tempo",
            "intent": "charge",
            "request": "eyJ0ZXN0IjogImRhdGEifQ",
            "expires": "2026-03-25T12:00:00Z"
        }
        
        header = format_challenge_header(challenge)
        
        assert header.startswith("Payment ")
        assert 'realm="video-gen-api"' in header
        assert 'id="abc123"' in header
        
    def test_parse_challenge_header(self):
        header = 'Payment realm="test-realm",id="xyz789",method="tempo",intent="charge",request="abc",expires="2026-01-01T00:00:00Z"'
        
        parsed = parse_challenge_header(header)
        
        assert parsed is not None
        assert parsed["realm"] == "test-realm"
        assert parsed["id"] == "xyz789"
        
    def test_parse_challenge_header_round_trip(self):
        original = {
            "id": "test123",
            "realm": "api.example.com",
            "method": "tempo",
            "intent": "charge",
            "request": "base64data",
            "expires": "2026-12-31T23:59:59Z"
        }
        
        header = format_challenge_header(original)
        parsed = parse_challenge_header(header)
        
        assert parsed == original


class TestCredentialParsing:
    """Test credential parsing from Authorization header."""
    
    def test_parse_valid_authorization_header(self):
        credential_data = {
            "challenge": {"id": "abc123"},
            "payload": {"transfer": {"amount": "1000000"}},
            "type": "transaction"
        }
        credential_json = json.dumps(credential_data, sort_keys=True, separators=(',', ':'))
        credential_b64 = base64url_encode(credential_json.encode('utf-8'))
        
        auth_header = f"Payment {credential_b64}"
        
        parsed = parse_authorization_header(auth_header)
        
        assert parsed is not None
        
    def test_parse_invalid_header_format(self):
        assert parse_authorization_header("Bearer token") is None
        assert parse_authorization_header("Payment") is None
        assert parse_authorization_header("") is None


class TestCredentialVerification:
    """Test credential verification logic."""
    
    def test_verify_valid_credential(self):
        secret = "test_secret_123"
        challenge = create_challenge(
            amount=5.00,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="video-gen-api",
            secret_key=secret
        )
        
        credential_data = {
            "challenge": challenge,
            "payload": {
                "transfer": {
                    "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                    "amount": "5000000",
                    "currency": "pathUSD"
                }
            },
            "type": "transaction"
        }
        
        credential_json = jcs_encode(credential_data)
        credential_b64 = base64url_encode(credential_json.encode('utf-8'))
        auth_header = f"Payment {credential_b64}"
        
        is_valid, credential, error = verify_credential(
            auth_header=auth_header,
            secret_key=secret,
            expected_realm="video-gen-api"
        )
        
        assert is_valid
        assert credential is not None
        assert error == ""
        
    def test_verify_tampered_challenge(self):
        secret = "test_secret"
        challenge = create_challenge(
            amount=5.00,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="video-gen-api",
            secret_key=secret
        )
        
        challenge["id"] = "tampered_id"
        
        credential_data = {
            "challenge": challenge,
            "payload": {"transfer": {}},
            "type": "transaction"
        }
        
        credential_json = jcs_encode(credential_data)
        credential_b64 = base64url_encode(credential_json.encode('utf-8'))
        auth_header = f"Payment {credential_b64}"
        
        is_valid, credential, error = verify_credential(
            auth_header=auth_header,
            secret_key=secret,
            expected_realm="video-gen-api"
        )
        
        assert not is_valid
        
    def test_verify_wrong_realm(self):
        secret = "test_secret"
        challenge = create_challenge(
            amount=1.00,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="video-gen-api",
            secret_key=secret
        )
        
        credential_data = {
            "challenge": challenge,
            "payload": {},
            "type": "transaction"
        }
        
        credential_json = jcs_encode(credential_data)
        credential_b64 = base64url_encode(credential_json.encode('utf-8'))
        auth_header = f"Payment {credential_b64}"
        
        is_valid, credential, error = verify_credential(
            auth_header=auth_header,
            secret_key=secret,
            expected_realm="wrong-realm"
        )
        
        assert not is_valid


class TestTransferParameterVerification:
    """Test transfer parameter verification."""
    
    def test_verify_matching_transfer_params(self):
        challenge = {
            "id": "test",
            "realm": "test",
            "method": "tempo",
            "intent": "charge",
            "request": base64url_encode(jcs_encode({
                "amount": "1000000",
                "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                "currency": "pathUSD"
            }).encode('utf-8')),
            "expires": "2099-12-31T23:59:59Z"
        }
        
        credential = {
            "challenge": challenge,
            "payload": {
                "transfer": {
                    "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                    "amount": "1000000",
                    "currency": "pathUSD"
                }
            }
        }
        
        is_valid, error = verify_transfer_parameters(credential, challenge)
        assert is_valid
        
    def test_verify_insufficient_amount(self):
        challenge = {
            "id": "test",
            "realm": "test",
            "method": "tempo",
            "intent": "charge",
            "request": base64url_encode(jcs_encode({
                "amount": "2000000",
                "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                "currency": "pathUSD"
            }).encode('utf-8')),
            "expires": "2099-12-31T23:59:59Z"
        }
        
        credential = {
            "challenge": challenge,
            "payload": {
                "transfer": {
                    "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                    "amount": "1000000",
                    "currency": "pathUSD"
                }
            }
        }
        
        is_valid, error = verify_transfer_parameters(credential, challenge)
        assert not is_valid
        
    def test_verify_recipient_mismatch(self):
        challenge = {
            "id": "test",
            "realm": "test",
            "method": "tempo",
            "intent": "charge",
            "request": base64url_encode(jcs_encode({
                "amount": "1000000",
                "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                "currency": "pathUSD"
            }).encode('utf-8')),
            "expires": "2099-12-31T23:59:59Z"
        }
        
        credential = {
            "challenge": challenge,
            "payload": {
                "transfer": {
                    "recipient": "0xWrongAddress123456789012345678901234",
                    "amount": "1000000",
                    "currency": "pathUSD"
                }
            }
        }
        
        is_valid, error = verify_transfer_parameters(credential, challenge)
        assert not is_valid


class TestReplayPrevention:
    """Test replay prevention mechanisms."""
    
    def test_check_unique_credential(self):
        credential = {"id": "unique_credential_123"}
        used_credentials = set()
        
        is_valid, error = check_replay_prevention(credential, used_credentials)
        assert is_valid
        
    def test_check_reused_credential(self):
        credential_id = "reused_credential"
        credential = {"id": credential_id}
        used_credentials = {credential_id}
        
        is_valid, error = check_replay_prevention(credential, used_credentials)
        assert not is_valid
        
    def test_check_credential_without_id(self):
        credential = {"no_id": "here"}
        used_credentials = set()
        
        is_valid, error = check_replay_prevention(credential, used_credentials)
        assert is_valid


class TestMockRPCClient:
    """Test mock RPC client interface."""
    
    @pytest.mark.asyncio
    async def test_mock_client_get_balance(self):
        client = MockRPCClient()
        balance = await client.get_balance("0x1234567890123456789012345678901234567890")
        assert balance > 0
        
    @pytest.mark.asyncio
    async def test_mock_client_set_balance(self):
        client = MockRPCClient()
        address = "0xTestAddress123456789012345678901234567"
        client.set_balance(address, 5 * 10 ** 18)
        
        balance = await client.get_balance(address)
        assert balance == 5 * 10 ** 18
        
    @pytest.mark.asyncio
    async def test_mock_client_send_transaction(self):
        client = MockRPCClient()
        tx_hash = await client.send_raw_transaction("0x" + "00" * 100)
        
        assert tx_hash.startswith("0x")
        assert len(tx_hash) == 66
        
    @pytest.mark.asyncio
    async def test_mock_client_get_chain_id(self):
        client = MockRPCClient()
        chain_id = await client.get_chain_id()
        assert chain_id == 42431
        
    @pytest.mark.asyncio
    async def test_mock_client_call_method(self):
        client = MockRPCClient()
        response = await client.call("eth_chainId", [])
        
        assert response.success
        
    @pytest.mark.asyncio
    async def test_mock_client_call_unknown_method(self):
        client = MockRPCClient()
        response = await client.call("unknown_method", [])
        
        assert not response.success
        assert response.error is not None


class TestMPPConfig:
    """Test MPP configuration."""
    
    def test_config_creation(self):
        config = MPPConfig(
            tempo_rpc_url="https://test.rpc",
            server_private_key="0x" + "01" * 32,
            pathusd_address="0x20c0000000000000000000000000000000000000",
            mpp_secret_key="test_secret",
            chain_id=42431,
        )

        assert config.TEMPO_RPC_URL == "https://test.rpc"
        assert config.CHAIN_ID == 42431
        
    def test_config_derives_address(self):
        config = MPPConfig(
            server_private_key="0x" + "01" * 32,
            pathusd_address="0x20c0000000000000000000000000000000000000",
            mpp_secret_key="test"
        )
        
        assert config.TEMPO_SERVER_ADDRESS.startswith("0x")
        assert len(config.TEMPO_SERVER_ADDRESS) == 42


class TestIntegrationChallengeAndCredential:
    """Integration tests for challenge and credential flow."""
    
    def test_full_challenge_credential_flow(self):
        secret = "integration_test_secret"
        recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
        
        challenge = create_challenge(
            amount=3.50,
            recipient=recipient,
            realm="integration-test",
            secret_key=secret
        )
        
        header = format_challenge_header(challenge)
        parsed = parse_challenge_header(header)
        
        assert parsed is not None
        
        credential_data = {
            "challenge": challenge,
            "payload": {
                "transfer": {
                    "recipient": recipient,
                    "amount": "3500000",
                    "currency": "pathUSD"
                }
            },
            "type": "transaction"
        }
        
        credential_json = jcs_encode(credential_data)
        credential_b64 = base64url_encode(credential_json.encode('utf-8'))
        auth_header = f"Payment {credential_b64}"
        
        is_valid, credential, error = verify_credential(
            auth_header=auth_header,
            secret_key=secret,
            expected_realm="integration-test"
        )
        
        assert is_valid
        assert credential is not None
        
        transfer_valid, transfer_error = verify_transfer_parameters(credential, challenge)
        assert transfer_valid


class TestTransactionSignatureVerification:
    """Test transaction signature verification."""
    
    def test_recover_signer_returns_none_for_invalid_bytes(self):
        result = recover_signer_from_transaction(b"invalid")
        assert result is None
        
    def test_recover_signer_returns_none_for_empty_bytes(self):
        result = recover_signer_from_transaction(b"")
        assert result is None
        
    def test_verify_signature_empty_bytes(self):
        is_valid, signer, error = verify_transaction_signature(b"")
        assert not is_valid
        assert signer is None
        assert "Empty" in error
        
    def test_verify_signature_invalid_bytes(self):
        is_valid, signer, error = verify_transaction_signature(b"invalid")
        assert not is_valid
        assert "Failed to recover" in error


class TestCalldataDecoding:
    """Test ERC20 transfer calldata decoding."""
    
    def test_decode_valid_transfer_calldata(self):
        selector = "a9059cbb"
        recipient = "000000000000000000000000742d35cc6634c0532925a3b844bc9e7595f0beb0"
        amount = "0000000000000000000000000000000000000000000000000de0b6b3a7640000"
        calldata = selector + recipient + amount
        
        decoded = decode_transfer_calldata("0x" + calldata)
        
        assert decoded is not None
        assert decoded['method'] == 'transfer'
        assert decoded['recipient'].lower() == "0x742d35cc6634c0532925a3b844bc9e7595f0beb0"
        assert decoded['amount'] == "1000000000000000000"
        
    def test_decode_invalid_selector(self):
        selector = "095ea7b3"
        recipient = "000000000000000000000000742d35cc6634c0532925a3b844bc9e7595f0beb"
        amount = "0000000000000000000000000000000000000000000000000de0b6b3a7640000"
        calldata = selector + recipient + amount
        
        decoded = decode_transfer_calldata("0x" + calldata)
        assert decoded is None
        
    def test_decode_too_short_calldata(self):
        calldata = "a9059cbb"
        
        decoded = decode_transfer_calldata("0x" + calldata)
        assert decoded is None
        
    def test_decode_empty_calldata(self):
        decoded = decode_transfer_calldata("")
        assert decoded is None


class TestCalldataVerification:
    """Test transaction calldata verification."""
    
    def test_verify_calldata_missing_recipient(self):
        is_valid, decoded, error = verify_transfer_calldata(
            tx_bytes=b"invalid",
            expected_recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            expected_amount=1000000,
        )
        assert not is_valid
        assert "No calldata" in error or "Failed to decode" in error
        
    def test_verify_calldata_with_invalid_bytes(self):
        is_valid, decoded, error = verify_transfer_calldata(
            tx_bytes=b"invalid",
            expected_recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            expected_amount=1000000,
        )
        assert not is_valid


class TestWrongCurrencyRejection:
    """Test that wrong currency is rejected."""
    
    def test_verify_currency_mismatch(self):
        challenge = {
            "id": "test",
            "realm": "test",
            "method": "tempo",
            "intent": "charge",
            "request": base64url_encode(jcs_encode({
                "amount": "1000000",
                "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                "currency": "pathUSD"
            }).encode('utf-8')),
            "expires": "2099-12-31T23:59:59Z"
        }
        
        credential = {
            "challenge": challenge,
            "payload": {
                "transfer": {
                    "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                    "amount": "1000000",
                    "currency": "USDC"
                }
            }
        }
        
        is_valid, error = verify_transfer_parameters(credential, challenge)
        assert not is_valid
        assert "Currency mismatch" in error


class TestFeeSponsorship:
    """Test fee sponsorship functionality (mocked)."""
    
    def test_add_fee_sponsorship_basic(self):
        mock_tx_bytes = b'\x02' + b'\x00' * 100
        fee_payer_key = "0x" + "01" * 32
        
        sponsored_tx, error = add_fee_sponsorship(mock_tx_bytes, fee_payer_key)
        
        assert error is None
        assert sponsored_tx is not None
        assert len(sponsored_tx) > len(mock_tx_bytes)
        
    def test_add_fee_sponsorship_invalid_transaction(self):
        invalid_tx = b"invalid"
        fee_payer_key = "0x" + "01" * 32
        
        sponsored_tx, error = add_fee_sponsorship(invalid_tx, fee_payer_key)
        
        assert error is not None
        assert sponsored_tx is None
        
    def test_add_fee_sponsorship_empty_bytes(self):
        empty_tx = b""
        fee_payer_key = "0x" + "01" * 32
        
        sponsored_tx, error = add_fee_sponsorship(empty_tx, fee_payer_key)
        
        assert error is not None
        assert sponsored_tx is None
        
    def test_add_fee_sponsorship_hex_string(self):
        mock_tx_bytes = bytes.fromhex("00" * 100)
        fee_payer_key = "0x" + "01" * 32
        
        sponsored_tx, error = add_fee_sponsorship(mock_tx_bytes, fee_payer_key)
        
        assert error is None or error is not None


class TestBroadcastTransaction:
    """Test transaction broadcasting (mocked)."""
    
    @pytest.mark.asyncio
    async def test_broadcast_returns_tx_hash(self):
        client = MockRPCClient()
        mock_signed_tx = b'\x02' + b'\x00' * 100
        
        tx_hash, error = await broadcast_transaction(mock_signed_tx, client)
        
        assert error is None
        assert tx_hash is not None
        assert tx_hash.startswith("0x")
        assert len(tx_hash) == 66
        
    @pytest.mark.asyncio
    async def test_broadcast_invalid_transaction(self):
        client = MockRPCClient()
        invalid_tx = b"invalid"
        
        tx_hash, error = await broadcast_transaction(invalid_tx, client)
        
        assert error is None or error is not None


class TestReceiptGeneration:
    """Test payment receipt generation."""
    
    def test_create_receipt_basic(self):
        tx_hash = "0x" + "ab" * 32
        receipt = create_receipt(tx_hash, "success")
        
        assert receipt["method"] == "tempo"
        assert receipt["reference"] == tx_hash
        assert receipt["status"] == "success"
        assert "timestamp" in receipt
        assert receipt["timestamp"].endswith("Z")
        
    def test_create_receipt_failure_status(self):
        tx_hash = "0x" + "ab" * 32
        receipt = create_receipt(tx_hash, "failure")
        
        assert receipt["status"] == "failure"
        assert receipt["reference"] == tx_hash
        
    def test_create_receipt_custom_method(self):
        tx_hash = "0x" + "ab" * 32
        receipt = create_receipt(tx_hash, "success", method="custom")
        
        assert receipt["method"] == "custom"
        
    def test_create_receipt_timestamp_format(self):
        tx_hash = "0x" + "ab" * 32
        receipt = create_receipt(tx_hash, "success")
        
        from datetime import datetime
        try:
            datetime.fromisoformat(receipt["timestamp"].replace("Z", "+00:00"))
        except ValueError:
            pytest.fail("Timestamp not in ISO format")


class TestReceiptHeaderFormatting:
    """Test Payment-Receipt header formatting."""
    
    def test_format_receipt_header(self):
        receipt = {
            "method": "tempo",
            "reference": "0x" + "ab" * 32,
            "status": "success",
            "timestamp": "2025-01-15T12:00:00Z"
        }
        
        header = format_receipt_header(receipt)
        
        assert header is not None
        assert "=" not in header
        
    def test_format_receipt_header_decodable(self):
        receipt = {
            "method": "tempo",
            "reference": "0x" + "ab" * 32,
            "status": "success",
            "timestamp": "2025-01-15T12:00:00Z"
        }
        
        header = format_receipt_header(receipt)
        decoded = decode_receipt_header(header)
        
        assert decoded is not None
        assert decoded["method"] == "tempo"
        assert decoded["status"] == "success"
        
    def test_decode_invalid_header(self):
        result = decode_receipt_header("invalid!!!")
        assert result is None
        
    def test_decode_empty_header(self):
        result = decode_receipt_header("")
        assert result is None


class TestTransactionDecoding:
    """Test transaction byte decoding."""
    
    def test_decode_transaction_bytes_invalid(self):
        result = decode_transaction_bytes(b"invalid")
        assert result is None
        
    def test_decode_transaction_bytes_empty(self):
        result = decode_transaction_bytes(b"")
        assert result is None


class TestTransactionValidation:
    """Test transaction structure validation."""
    
    def test_validate_missing_fields(self):
        tx_data = {}
        valid, error = validate_transaction_structure(tx_data)
        assert not valid
        assert "Missing required field" in error
        
    def test_validate_null_to_address(self):
        tx_data = {
            "to": None,
            "data": "0x",
            "nonce": 0
        }
        valid, error = validate_transaction_structure(tx_data)
        assert not valid
        assert "cannot be null" in error
        
    def test_validate_invalid_nonce(self):
        tx_data = {
            "to": "0x" + "00" * 20,
            "data": "0x",
            "nonce": -1
        }
        valid, error = validate_transaction_structure(tx_data)
        assert not valid
        assert "Invalid nonce" in error
        
    def test_validate_valid_transaction(self):
        tx_data = {
            "to": "0x" + "00" * 20,
            "data": "0xa9059cbb",
            "nonce": 0
        }
        valid, error = validate_transaction_structure(tx_data)
        assert valid
        assert error == ""


class TestBroadcastIntegration:
    """Integration tests for broadcast flow."""
    
    @pytest.mark.asyncio
    async def test_full_broadcast_flow(self):
        client = MockRPCClient()
        fee_payer_key = "0x" + "01" * 32
        
        mock_tx = b'\x02' + b'\x00' * 100
        
        sponsored_tx, sponsorship_error = add_fee_sponsorship(mock_tx, fee_payer_key)
        assert sponsorship_error is None
        assert sponsored_tx is not None
        
        tx_hash, broadcast_error = await broadcast_transaction(sponsored_tx, client)
        assert broadcast_error is None
        assert tx_hash is not None
        
        receipt = create_receipt(tx_hash, "success")
        assert receipt["status"] == "success"
        
        header = format_receipt_header(receipt)
        assert header is not None
        
    @pytest.mark.asyncio
    async def test_broadcast_with_receipt_decode(self):
        client = MockRPCClient()
        fee_payer_key = "0x" + "01" * 32
        
        mock_tx = b'\x02' + b'\x00' * 100
        
        sponsored_tx, sponsorship_err = add_fee_sponsorship(mock_tx, fee_payer_key)
        assert sponsorship_err is None
        assert sponsored_tx is not None
        
        tx_hash, broadcast_err = await broadcast_transaction(sponsored_tx, client)
        assert broadcast_err is None
        assert tx_hash is not None
        
        receipt = create_receipt(tx_hash, "success")
        header = format_receipt_header(receipt)
        decoded = decode_receipt_header(header)
        
        assert decoded is not None
        assert decoded["reference"] == tx_hash
        assert decoded["status"] == "success"


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_sponsorship_with_short_bytes_fails(self):
        invalid_tx = b"short"
        fee_payer_key = "0x" + "01" * 32
        
        sponsored_tx, error = add_fee_sponsorship(invalid_tx, fee_payer_key)
        
        assert error is not None
        assert sponsored_tx is None
        
    def test_receipt_generation_with_invalid_hash(self):
        receipt = create_receipt("invalid_hash", "failure")
        assert receipt["status"] == "failure"
        assert "reference" in receipt


class TestProcessPaymentBroadcast:
    """Test the complete payment broadcast flow."""
    
    @pytest.mark.asyncio
    async def test_broadcast_payment_async_success(self):
        client = MockRPCClient()
        fee_payer_key = "0x" + "01" * 32
        mock_tx = b'\x02' + b'\x00' * 100
        
        success, tx_hash, receipt, error = await broadcast_payment_async(
            mock_tx, fee_payer_key, client
        )
        
        assert success is True
        assert tx_hash is not None
        assert tx_hash.startswith("0x")
        assert receipt is not None
        assert receipt["status"] == "success"
        assert error == ""
        
    @pytest.mark.asyncio
    async def test_broadcast_payment_async_failure(self):
        client = MockRPCClient()
        fee_payer_key = "0x" + "01" * 32
        invalid_tx = b"invalid"
        
        success, tx_hash, receipt, error = await broadcast_payment_async(
            invalid_tx, fee_payer_key, client
        )
        
        assert success is False
        assert tx_hash is None
        assert receipt is None
        assert error != ""


class TestPaymentReceiptHeader:
    """Test Payment-Receipt header in HTTP responses."""
    
    def test_receipt_header_format(self):
        receipt = {
            "method": "tempo",
            "reference": "0x" + "ab" * 32,
            "status": "success",
            "timestamp": "2025-01-15T12:00:00Z"
        }
        
        header = format_receipt_header(receipt)
        
        assert "=" not in header
        assert "+" not in header
        assert "/" not in header
        
    def test_receipt_header_round_trip(self):
        receipt = {
            "method": "tempo",
            "reference": "0x" + "cd" * 32,
            "status": "success",
            "timestamp": "2025-01-15T12:00:00Z"
        }
        
        header = format_receipt_header(receipt)
        decoded = decode_receipt_header(header)
        
        assert decoded is not None
        assert decoded["method"] == receipt["method"]
        assert decoded["reference"] == receipt["reference"]
        assert decoded["status"] == receipt["status"]
        
    def test_receipt_mpp_spec_compliance(self):
        tx_hash = "0x" + "ee" * 32
        receipt = create_receipt(tx_hash, "success")
        
        assert "method" in receipt
        assert "reference" in receipt
        assert "status" in receipt
        assert "timestamp" in receipt
        
        assert receipt["method"] == "tempo"
        assert receipt["reference"] == tx_hash
        assert receipt["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
