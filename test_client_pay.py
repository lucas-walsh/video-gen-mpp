"""
Client Payment Script Tests

Tests for client-pay.py payment flow:
- Challenge decoding
- TIP-20 transaction creation
- Transaction signing (domain 0x76)
- Credential encoding
- Error handling
"""

import sys
import os
import importlib.util
import pytest
import json
import base64
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from eth_hash.auto import keccak

from eth_hash.auto import keccak

test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, test_dir)

spec = importlib.util.spec_from_file_location(
    "client_pay",
    os.path.join(test_dir, "client-pay.py")
)
client_pay = importlib.util.module_from_spec(spec)  # type: ignore
spec.loader.exec_module(client_pay)  # type: ignore

from eth_account import Account
from mpp.challenge import (
    create_challenge,
    format_challenge_header,
    decode_challenge_request,
    base64url_encode,
    base64url_decode,
)
from mpp.credential import create_credential, parse_authorization_header


class TestChallengeDecoding:
    """Test challenge parsing and decoding."""
    
    def test_decode_challenge_request(self):
        """Test decoding challenge request from base64url."""
        request_params = {
            "amount": "0.600000",
            "currency": "pathUSD",
            "currency_address": "0x20c0000000000000000000000000000000000000",
            "method": "tempo",
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            "realm": "video-gen-api",
            "timestamp": "2024-01-15T12:00:00+00:00",
        }
        
        request_jcs = json.dumps(
            request_params,
            sort_keys=True,
            separators=(',', ':')
        )
        request_b64 = base64url_encode(request_jcs.encode('utf-8'))
        
        challenge = {
            "id": "abc123",
            "realm": "video-gen-api",
            "method": "tempo",
            "intent": "charge",
            "request": request_b64,
            "expires": "2024-01-15T12:05:00+00:00",
        }
        
        decoded = decode_challenge_request(challenge)
        
        assert decoded is not None
        assert decoded["amount"] == "0.600000"
        assert decoded["currency"] == "pathUSD"
        assert decoded["recipient"] == "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
        
    def test_decode_invalid_request(self):
        """Test decoding invalid request returns None."""
        challenge = {
            "request": "invalid_base64!!!",
        }
        
        decoded = decode_challenge_request(challenge)
        assert decoded is None
        
    def test_parse_challenge_header(self):
        """Test parsing WWW-Authenticate header."""
        header_value = (
            'Payment realm="video-gen-api", '
            'id="abc123", '
            'method="tempo", '
            'intent="charge", '
            'request="eyJhbW91bnQiOiIwLjYifQ", '
            'expires="2024-01-15T12:05:00+00:00"'
        )
        
        from mpp.challenge import parse_challenge_header
        parsed = parse_challenge_header(header_value)
        
        assert parsed is not None
        assert parsed["realm"] == "video-gen-api"
        assert parsed["id"] == "abc123"
        assert parsed["method"] == "tempo"
        assert parsed["intent"] == "charge"


class TestTIP20TransactionCreation:
    """Test TIP-20 transaction creation."""
    
    def test_encode_transfer_calldata(self):
        """Test encoding transfer(address,uint256) function call."""
        encode_transfer_calldata = client_pay.encode_transfer_calldata
        
        recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
        amount = "600000"
        
        calldata = encode_transfer_calldata(recipient, amount)
        
        function_selector = keccak(
            b"transfer(address,uint256)"
        ).hex()[:8]
        
        assert calldata.startswith(function_selector)
        assert len(calldata) == 8 + 64 + 64
        
    def test_encode_transfer_calldata_without_0x(self):
        """Test encoding with recipient without 0x prefix."""
        encode_transfer_calldata = client_pay.encode_transfer_calldata
        
        recipient = "742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
        amount = "600000"
        
        calldata = encode_transfer_calldata(recipient, amount)
        
        assert len(calldata) == 8 + 64 + 64
        
    def test_create_tempo_transaction(self):
        """Test creating Tempo transaction structure."""
        create_tempo_transaction = client_pay.create_tempo_transaction
        PATHUSD_ADDRESS = client_pay.PATHUSD_ADDRESS
        
        recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
        amount = "600000"
        sender = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
        
        transaction = create_tempo_transaction(
            recipient=recipient,
            amount=amount,
            sender_address=sender,
            nonce=0,
            chain_id=57059,
        )
        
        assert transaction["type"] == "0x76"
        assert transaction["chainId"] == 57059
        assert transaction["nonce"] == 0
        assert transaction["to"] == PATHUSD_ADDRESS
        assert transaction["value"] == "0x0"
        assert transaction["data"].startswith("0x")
        assert "validBefore" in transaction
        assert transaction["feeToken"] == PATHUSD_ADDRESS
        assert transaction["feePayer"] == sender
        assert transaction["feePayerSignature"] == "0x"
        
    def test_create_tempo_transaction_custom_params(self):
        """Test creating transaction with custom parameters."""
        create_tempo_transaction = client_pay.create_tempo_transaction
        
        transaction = create_tempo_transaction(
            recipient="0x123",
            amount="1000000",
            sender_address="0x456",
            nonce=5,
            chain_id=1,
            valid_before=1234567890,
        )
        
        assert transaction["nonce"] == 5
        assert transaction["chainId"] == 1
        assert transaction["validBefore"] == 1234567890


class TestTransactionSigning:
    """Test transaction signing with domain 0x76."""
    
    def test_encode_transaction_for_signing(self):
        """Test encoding transaction for signing."""
        encode_transaction_for_signing = client_pay.encode_transaction_for_signing
        
        transaction = {
            "chainId": 57059,
            "nonce": 0,
            "to": "0x20c0000000000000000000000000000000000000",
            "value": "0x0",
            "data": "0xabcdef",
            "validBefore": 1234567890,
            "feeToken": "0x20c0000000000000000000000000000000000000",
            "feePayer": "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
        }
        
        encoded = encode_transaction_for_signing(transaction)
        
        assert isinstance(encoded, bytes)
        assert len(encoded) == 256
        
    def test_sign_transaction_domain_0x76(self):
        """Test signing transaction with domain 0x76."""
        sign_transaction = client_pay.sign_transaction
        create_tempo_transaction = client_pay.create_tempo_transaction
        
        private_key = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
        account = Account.from_key(private_key)
        sender_address = account.address
        
        transaction = create_tempo_transaction(
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            amount="600000",
            sender_address=sender_address,
            nonce=0,
        )
        
        signature, tx_hash = sign_transaction(transaction, private_key, domain=0x76)
        
        assert signature.startswith("0x")
        assert len(signature) == 134
        
        assert tx_hash.startswith("0x")
        assert len(tx_hash) == 66
        
    def test_sign_transaction_without_0x_prefix(self):
        """Test signing with private key without 0x prefix."""
        sign_transaction = client_pay.sign_transaction
        create_tempo_transaction = client_pay.create_tempo_transaction
        
        private_key = "4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
        account = Account.from_key("0x" + private_key)
        sender_address = account.address
        
        transaction = create_tempo_transaction(
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            amount="600000",
            sender_address=sender_address,
            nonce=0,
        )
        
        signature, tx_hash = sign_transaction(transaction, private_key)
        
        assert signature.startswith("0x")
        assert tx_hash.startswith("0x")
        
    def test_sign_transaction_deterministic(self):
        """Test that signing is deterministic."""
        sign_transaction = client_pay.sign_transaction
        create_tempo_transaction = client_pay.create_tempo_transaction
        
        private_key = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
        account = Account.from_key(private_key)
        sender_address = account.address
        
        transaction = create_tempo_transaction(
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            amount="600000",
            sender_address=sender_address,
            nonce=0,
            valid_before=1234567890,
        )
        
        sig1, hash1 = sign_transaction(transaction, private_key)
        sig2, hash2 = sign_transaction(transaction, private_key)
        
        assert sig1 == sig2
        assert hash1 == hash2


class TestCredentialEncoding:
    """Test credential creation and encoding."""
    
    def test_create_credential_with_challenge_echo(self):
        """Test creating credential with full challenge echo."""
        create_tempo_transaction = client_pay.create_tempo_transaction
        PATHUSD_ADDRESS = client_pay.PATHUSD_ADDRESS
        sign_transaction = client_pay.sign_transaction
        
        private_key = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
        account = Account.from_key(private_key)
        sender_address = account.address
        
        challenge = create_challenge(
            amount=0.60,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="video-gen-api",
            method="tempo",
            secret_key="test-secret-key",
        )
        
        transaction = create_tempo_transaction(
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            amount="600000",
            sender_address=sender_address,
            nonce=0,
        )
        
        signature, tx_hash = sign_transaction(transaction, private_key)
        
        transfer_params = {
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            "amount": "600000",
            "currency": "pathUSD",
        }
        
        credential_b64 = create_credential(
            challenge=challenge,
            transaction_hash=tx_hash,
            transfer_params=transfer_params,
        )
        
        credential_json = base64url_decode(credential_b64).decode('utf-8')
        credential = json.loads(credential_json)
        
        assert "challenge" in credential
        assert credential["challenge"]["id"] == challenge["id"]
        assert credential["challenge"]["realm"] == challenge["realm"]
        assert credential["challenge"]["method"] == challenge["method"]
        assert credential["challenge"]["intent"] == challenge["intent"]
        assert credential["challenge"]["request"] == challenge["request"]
        assert credential["challenge"]["expires"] == challenge["expires"]
        
        assert credential["type"] == "transaction"
        assert "payload" in credential
        assert credential["payload"]["transaction_hash"] == tx_hash
        assert credential["payload"]["transfer"] == transfer_params
        
    def test_parse_authorization_header(self):
        """Test parsing Authorization header."""
        private_key = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
        account = Account.from_key(private_key)
        sender_address = account.address
        
        challenge = create_challenge(
            amount=0.60,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="video-gen-api",
            method="tempo",
            secret_key="test-secret-key",
        )
        
        create_tempo_transaction = client_pay.create_tempo_transaction
        sign_transaction = client_pay.sign_transaction
        
        transaction = create_tempo_transaction(
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            amount="600000",
            sender_address=sender_address,
            nonce=0,
        )
        
        signature, tx_hash = sign_transaction(transaction, private_key)
        
        transfer_params = {
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            "amount": "600000",
            "currency": "pathUSD",
        }
        
        credential_b64 = create_credential(
            challenge=challenge,
            transaction_hash=tx_hash,
            transfer_params=transfer_params,
        )
        
        auth_header = f"Payment {credential_b64}"
        parsed = parse_authorization_header(auth_header)
        
        assert parsed is not None
        assert parsed["type"] == "transaction"
        assert "challenge" in parsed
        assert "payload" in parsed


class TestHTTPClient:
    """Test HTTP client interactions."""
    
    @patch.object(client_pay.httpx, 'Client')
    def test_make_initial_request_402(self, mock_client_class):
        """Test making initial request that returns 402."""
        make_initial_request = client_pay.make_initial_request
        
        mock_response = Mock()
        mock_response.status_code = 402
        mock_response.headers = {
            "WWW-Authenticate": (
                'Payment realm="video-gen-api", '
                'id="abc123", '
                'method="tempo", '
                'intent="charge", '
                'request="eyJhbW91bnQiOiIwLjYwMDAwMCIsImN1cnJlbmN5IjoicGF0aFVTRCIsIm1ldGhvZCI6InRlbXBvIiwicmVjaXBpZW50IjoiMHg3NDJkMzVDYzY2MzRDMDUzMjkyNWEzYjg0NEJjOWU3NTk1ZjBiRWIiLCJyZWFsbSI6InZpZGVvLWdlbi1hcGkiLCJ0aW1lc3RhbXAiOiIyMDI0LTAxLTE1VDEyOjAwOjAwKzAwOjAwIn0", '
                'expires="2024-01-15T12:05:00+00:00"'
            )
        }
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_client.post = Mock(return_value=mock_response)
        mock_client_class.return_value = mock_client
        
        challenge, www_auth, error, session_id = make_initial_request(
            api_url="http://localhost:8000",
            prompt="Test prompt",
            duration=5,
        )
        
        assert challenge is not None
        assert challenge["id"] == "abc123"
        assert error == ""
        
    @patch.object(client_pay.httpx, 'Client')
    def test_make_initial_request_200(self, mock_client_class):
        """Test making initial request that returns 200 (unexpected)."""
        make_initial_request = client_pay.make_initial_request
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"success": True})
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_client.post = Mock(return_value=mock_response)
        mock_client_class.return_value = mock_client
        
        challenge, www_auth, error, session_id = make_initial_request(
            api_url="http://localhost:8000",
            prompt="Test prompt",
            duration=5,
        )
        
        assert challenge is None
        assert "Unexpected 200" in error
        
    @patch.object(client_pay.httpx, 'Client')
    def test_make_initial_request_503(self, mock_client_class):
        """Test making initial request that returns 503."""
        make_initial_request = client_pay.make_initial_request
        
        mock_response = Mock()
        mock_response.status_code = 503
        mock_response.json = Mock(return_value={
            "success": False,
            "error": "Service unavailable"
        })
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_client.post = Mock(return_value=mock_response)
        mock_client_class.return_value = mock_client
        
        challenge, www_auth, error, session_id = make_initial_request(
            api_url="http://localhost:8000",
            prompt="Test prompt",
            duration=5,
        )
        
        assert challenge is None
        assert "Service unavailable" in error
        
    @patch.object(client_pay.httpx, 'Client')
    def test_send_payment_request_401(self, mock_client_class):
        """Test sending payment request that returns 401."""
        send_payment_request = client_pay.send_payment_request
        
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json = Mock(return_value={
            "success": False,
            "error": "Invalid credential"
        })
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_client.post = Mock(return_value=mock_response)
        mock_client_class.return_value = mock_client
        
        response_data, error = send_payment_request(
            api_url="http://localhost:8000",
            prompt="Test",
            duration=5,
            model="fal-ai/veo3.1/fast",
            credential_b64="invalid_credential",
            session_id="quote_abc123",
        )
        
        assert response_data is None
        assert "Unauthorized" in error


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_invalid_private_key_raises_error(self):
        """Test that invalid private key raises ValueError during signing."""
        create_tempo_transaction = client_pay.create_tempo_transaction
        sign_transaction = client_pay.sign_transaction
        
        transaction = create_tempo_transaction(
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            amount="600000",
            sender_address="0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            nonce=0,
        )
        
        with pytest.raises(ValueError):
            sign_transaction(transaction, "invalid_key")
            
    @patch.object(client_pay.httpx, 'Client')
    def test_network_error(self, mock_client_class):
        """Test handling network errors."""
        make_initial_request = client_pay.make_initial_request
        import httpx
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_client.post = Mock(side_effect=httpx.RequestError("Network error"))
        mock_client_class.return_value = mock_client
        
        challenge, www_auth, error, session_id = make_initial_request(
            api_url="http://localhost:8000",
            prompt="Test",
            duration=5,
        )
        
        assert challenge is None
        assert "Request failed" in error


class TestIntegration:
    """Integration tests for complete payment flow."""
    
    @patch.object(client_pay.httpx, 'Client')
    def test_full_payment_flow(self, mock_client_class):
        """Test complete payment flow with mocked HTTP."""
        run_payment_flow = client_pay.run_payment_flow
        
        private_key = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
        
        challenge = create_challenge(
            amount=0.60,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            realm="video-gen-api",
            method="tempo",
            secret_key="test-secret-key",
        )
        
        www_auth_header = format_challenge_header(challenge)
        
        mock_402_response = Mock()
        mock_402_response.status_code = 402
        mock_402_response.headers = {"WWW-Authenticate": www_auth_header}
        
        mock_200_response = Mock()
        mock_200_response.status_code = 200
        mock_200_response.json = Mock(return_value={
            "success": True,
            "job_id": "job_abc123",
            "status": "processing",
            "cost_usd": "0.60",
        })
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_client.post = Mock(
            side_effect=[mock_402_response, mock_200_response]
        )
        mock_client_class.return_value = mock_client
        
        result = run_payment_flow(
            api_url="http://localhost:8000",
            prompt="Test prompt",
            duration=5,
            private_key=private_key,
            verbose=False,
        )
        
        assert result["success"] is True
        assert result["job_id"] == "job_abc123"
        assert result["status"] == "processing"
        assert result["cost"] == "0.60"
        assert result["transaction_hash"] is not None
        assert result["error"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
