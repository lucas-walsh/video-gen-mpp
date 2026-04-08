"""
Main API Tests with MPP Integration

Tests for the video generation API with proper MPP payment verification.
"""

import pytest
import time
import uuid
import os
from unittest.mock import patch, AsyncMock, MagicMock

from httpx import AsyncClient
from main import app, quote_sessions, cleanup_expired_sessions, calculate_final_price, jobs_db, last_poll_time
from config import MARKUP_PERCENT, QUOTE_TTL_SECONDS, SUPPORTED_VIDEO_MODELS, DEFAULT_VIDEO_MODEL
from mpp.config import MPPConfig, reset_config
from mpp.challenge import create_challenge, format_challenge_header
from mpp.broadcast import create_receipt, format_receipt_header, decode_receipt_header
from mpp.broadcast import create_receipt, format_receipt_header, decode_receipt_header


@pytest.fixture
async def client():
    quote_sessions.clear()
    jobs_db.clear()
    last_poll_time.clear()
    reset_config()
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_fal_pricing():
    with patch("main.get_fal_pricing", new_callable=AsyncMock) as mock:
        mock.return_value = (0.05, "second")
        yield mock


@pytest.fixture
def mock_submit_to_fal():
    with patch("main.submit_to_fal", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "request_id": "req_test123",
            "status": "IN_PROGRESS",
        }
        yield mock


@pytest.fixture
def mock_mpp_config():
    config = MPPConfig(
        tempo_rpc_url="https://test.rpc",
        server_private_key="0x" + "01" * 32,
        pathusd_address="0x20c0000000000000000000000000000000000000",
        mpp_secret_key="test_mpp_secret_key"
    )
    with patch("main.get_mpp_config", return_value=config):
        yield config


class TestHomepage:
    @pytest.mark.asyncio
    async def test_homepage_returns_api_info(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Video Generation API (MPP)"
        assert "endpoints" in data


class TestVideoGenerationWithoutPayment:
    @pytest.mark.asyncio
    async def test_generate_without_payment_returns_402(self, client, mock_fal_pricing, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "A beautiful sunset", "duration_seconds": 5}
        )
        assert response.status_code == 402
        data = response.json()
        assert data["type"] == "https://paymentauth.org/problems/payment-required"
        assert data["title"] == "Payment Required"
        assert data["status"] == 402
        assert "amount" in data
        assert "currency" in data
        assert "expires_in" in data
        assert "WWW-Authenticate" in response.headers
        assert 'Payment realm="video-gen-api"' in response.headers["WWW-Authenticate"]
        assert response.headers["Cache-Control"] == "no-store"
        
    @pytest.mark.asyncio
    async def test_402_response_problem_details_format(self, client, mock_fal_pricing, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test video", "duration_seconds": 10}
        )
        data = response.json()
        assert data["type"] == "https://paymentauth.org/problems/payment-required"
        assert data["title"] == "Payment Required"
        assert data["status"] == 402
        assert "$0.60" in data["detail"]
        assert "pathUSD" in data["detail"]
        
    @pytest.mark.asyncio
    async def test_challenge_amount_matches_fal_price_plus_markup(self, client, mock_mpp_config):
        fal_price_per_second = 0.05
        duration = 10
        expected_subtotal = fal_price_per_second * duration
        expected_total = expected_subtotal * (1 + MARKUP_PERCENT / 100)
        expected_amount_cents = int(expected_total * 1_000_000)
        
        with patch("main.get_fal_pricing", new_callable=AsyncMock) as mock_pricing:
            mock_pricing.return_value = (fal_price_per_second, "second")
            response = await client.post(
                "/api/video/generate",
                json={"prompt": "Test", "duration_seconds": duration}
            )
        
        data = response.json()
        assert data["amount"] == str(expected_amount_cents)


class TestMPPChallengeGeneration:
    @pytest.mark.asyncio
    async def test_challenge_has_required_fields(self, client, mock_fal_pricing, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        
        header = response.headers["WWW-Authenticate"]
        assert 'id="' in header
        assert 'realm="video-gen-api"' in header
        assert 'method="tempo"' in header
        assert 'intent="charge"' in header
        assert 'request="' in header
        assert 'expires="' in header
        
    @pytest.mark.asyncio
    async def test_challenge_request_is_base64url(self, client, mock_fal_pricing, mock_mpp_config):
        from mpp.challenge import base64url_decode, jcs_decode
        
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        
        header = response.headers["WWW-Authenticate"]
        request_start = header.find('request="') + len('request="')
        request_end = header.find('"', request_start)
        request_b64 = header[request_start:request_end]
        
        decoded = base64url_decode(request_b64)
        request_data = jcs_decode(decoded.decode('utf-8'))
        
        assert "amount" in request_data
        assert "recipient" in request_data
        assert "currency" in request_data
        
    @pytest.mark.asyncio
    async def test_challenge_hmac_binding(self, client, mock_fal_pricing, mock_mpp_config):
        from mpp.challenge import parse_challenge_header, verify_challenge_binding
        
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        
        header = response.headers["WWW-Authenticate"]
        challenge = parse_challenge_header(header)
        
        assert challenge is not None
        assert verify_challenge_binding(challenge, mock_mpp_config.MPP_SECRET_KEY)


class TestVideoGenerationWithPayment:
    @pytest.mark.asyncio
    async def test_generate_with_valid_payment_returns_200(self, client, mock_fal_pricing, mock_submit_to_fal, mock_mpp_config):
        with patch("main.verify_transfer_calldata", return_value=(True, {}, "")):
            with patch("main.verify_transaction_signature", return_value=(True, "0x" + "00" * 40, "")):
                initial_response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "A cat playing piano", "duration_seconds": 3}
                )
                assert initial_response.status_code == 402
                session_id = initial_response.json()["session_id"]
                challenge = quote_sessions[session_id]["challenge"]
                
                from mpp.credential import create_credential
                import json
                from mpp.challenge import base64url_encode, jcs_encode
                
                credential_data = {
                    "challenge": challenge,
                    "payload": {
                        "transfer": {
                            "recipient": mock_mpp_config.TEMPO_SERVER_ADDRESS,
                            "amount": str(int(quote_sessions[session_id]["final_price_total"] * 1_000_000)),
                            "currency": "pathUSD"
                        },
                        "transaction_bytes": "0x" + "00" * 200
                    },
                    "type": "transaction"
                }
                
                credential_json = jcs_encode(credential_data)
                credential_b64 = base64url_encode(credential_json.encode('utf-8'))
                
                retry_response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "A cat playing piano", "duration_seconds": 3},
                    headers={
                        "Authorization": f"Payment {credential_b64}",
                        "X-Session-ID": session_id
                    }
                )
                assert retry_response.status_code == 200
                data = retry_response.json()
                assert data["success"] is True
                assert "job_id" in data
        
    @pytest.mark.asyncio
    async def test_session_cleared_after_successful_payment(self, client, mock_fal_pricing, mock_submit_to_fal, mock_mpp_config):
        with patch("main.verify_transfer_calldata", return_value=(True, {}, "")):
            with patch("main.verify_transaction_signature", return_value=(True, "0x" + "00" * 40, "")):
                initial_response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 2}
                )
                session_id = initial_response.json()["session_id"]
                assert session_id in quote_sessions
                
                from mpp.challenge import base64url_encode, jcs_encode
                
                credential_data = {
                    "challenge": quote_sessions[session_id]["challenge"],
                    "payload": {
                        "transfer": {"recipient": mock_mpp_config.TEMPO_SERVER_ADDRESS, "amount": "1000000", "currency": "pathUSD"},
                        "transaction_bytes": "0x" + "00" * 200
                    },
                    "type": "transaction"
                }
                
                credential_json = jcs_encode(credential_data)
                credential_b64 = base64url_encode(credential_json.encode('utf-8'))
                
                await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 2},
                    headers={
                        "Authorization": f"Payment {credential_b64}",
                        "X-Session-ID": session_id
                    }
                )
                assert session_id not in quote_sessions


class TestInvalidPaymentCredential:
    @pytest.mark.asyncio
    async def test_invalid_session_id_returns_401(self, client, mock_fal_pricing, mock_mpp_config):
        from mpp.challenge import base64url_encode, jcs_encode
        
        challenge = create_challenge(
            amount=1.00,
            recipient=mock_mpp_config.TEMPO_SERVER_ADDRESS,
            realm="video-gen-api",
            secret_key=mock_mpp_config.MPP_SECRET_KEY
        )
        
        credential_data = {
            "challenge": challenge,
            "payload": {"transfer": {}},
            "type": "transaction"
        }
        credential_json = jcs_encode(credential_data)
        credential_b64 = base64url_encode(credential_json.encode('utf-8'))
        
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5},
            headers={
                "Authorization": f"Payment {credential_b64}",
                "X-Session-ID": "nonexistent_session"
            }
        )
        assert response.status_code == 401
        
    @pytest.mark.asyncio
    async def test_tampered_challenge_returns_401(self, client, mock_fal_pricing, mock_mpp_config):
        initial_response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        session_id = initial_response.json()["session_id"]
        challenge = quote_sessions[session_id]["challenge"]
        
        challenge["id"] = "tampered_id"
        
        from mpp.challenge import base64url_encode, jcs_encode
        credential_data = {
            "challenge": challenge,
            "payload": {"transfer": {}},
            "type": "transaction"
        }
        credential_json = jcs_encode(credential_data)
        credential_b64 = base64url_encode(credential_json.encode('utf-8'))
        
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5},
            headers={
                "Authorization": f"Payment {credential_b64}",
                "X-Session-ID": session_id
            }
        )
        assert response.status_code == 401


class TestReplayPrevention:
    @pytest.mark.asyncio
    async def test_reused_credential_rejected(self, client, mock_fal_pricing, mock_submit_to_fal, mock_mpp_config):
        with patch("main.verify_transfer_calldata", return_value=(True, {}, "")):
            with patch("main.verify_transaction_signature", return_value=(True, "0x" + "00" * 40, "")):
                from mpp.challenge import base64url_encode, jcs_encode
                
                initial_response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 2}
                )
                session_id = initial_response.json()["session_id"]
                challenge = quote_sessions[session_id]["challenge"]
                
                credential_id = challenge["id"]
                credential_data = {
                    "id": credential_id,
                    "challenge": challenge,
                    "payload": {
                        "transfer": {"recipient": mock_mpp_config.TEMPO_SERVER_ADDRESS, "amount": "1000000", "currency": "pathUSD"},
                        "transaction_bytes": "0x" + "00" * 200
                    },
                    "type": "transaction"
                }
                credential_json = jcs_encode(credential_data)
                credential_b64 = base64url_encode(credential_json.encode('utf-8'))
                
                response1 = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 2},
                    headers={
                        "Authorization": f"Payment {credential_b64}",
                        "X-Session-ID": session_id
                    }
                )
                assert response1.status_code == 200
        
        quote_sessions[session_id] = {
            "prompt": "Test",
            "duration_seconds": 2,
            "model": "fal-ai/veo3.1/fast",
            "final_price_total": 0.12,
            "expires_at": time.time() + 300,
            "challenge": challenge,
        }
        
        response2 = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 2},
            headers={
                "Authorization": f"Payment {credential_b64}",
                "X-Session-ID": session_id
            }
        )
        assert response2.status_code == 401
        assert "replay" in response2.json()["error"].lower()


class TestCleanupExpiredSessions:
    def test_cleanup_removes_expired_sessions(self):
        quote_sessions.clear()
        quote_sessions["expired_session"] = {
            "expires_at": time.time() - 100,
            "prompt": "old"
        }
        quote_sessions["valid_session"] = {
            "expires_at": time.time() + 300,
            "prompt": "new"
        }

        cleanup_expired_sessions()

        assert "expired_session" not in quote_sessions
        assert "valid_session" in quote_sessions


class TestCalculateFinalPrice:
    def test_calculate_final_price_with_markup(self):
        fal_price = 1.00
        expected = 1.00 * (1 + MARKUP_PERCENT / 100)
        assert calculate_final_price(fal_price) == expected

    def test_calculate_final_price_zero_base(self):
        assert calculate_final_price(0.0) == 0.0


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_boundary_duration_minimum(self, client, mock_fal_pricing, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 1}
        )
        assert response.status_code == 402
        data = response.json()
        assert data["expires_in"] == QUOTE_TTL_SECONDS
        
    @pytest.mark.asyncio
    async def test_boundary_duration_maximum(self, client, mock_fal_pricing, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 30}
        )
        assert response.status_code == 402
        data = response.json()
        assert data["expires_in"] == QUOTE_TTL_SECONDS
        
    @pytest.mark.asyncio
    async def test_longer_duration_higher_amount(self, client, mock_mpp_config):
        fal_price_per_second = 0.05
        
        with patch("main.get_fal_pricing", new_callable=AsyncMock) as mock_pricing:
            mock_pricing.return_value = (fal_price_per_second, "second")
            
            response_5s = await client.post(
                "/api/video/generate",
                json={"prompt": "Test", "duration_seconds": 5}
            )
            
            response_10s = await client.post(
                "/api/video/generate",
                json={"prompt": "Test", "duration_seconds": 10}
            )
        
        amount_5s = int(response_5s.json()["amount"])
        amount_10s = int(response_10s.json()["amount"])
        assert amount_10s > amount_5s
        assert amount_10s == amount_5s * 2
        
    @pytest.mark.asyncio
    async def test_different_models_different_prices(self, client, mock_mpp_config):
        model_prices = {
            "fal-ai/veo3.1/fast": 0.05,
            "fal-ai/veo3.1": 0.08,
            "fal-ai/kling/video/v2.5/pro": 0.10,
        }
        
        async def mock_pricing_func(endpoint_id):
            return model_prices.get(endpoint_id, 0.05), "second"
        
        with patch("main.get_fal_pricing", new_callable=AsyncMock) as mock_pricing:
            mock_pricing.side_effect = mock_pricing_func
            
            responses = {}
            for model, expected_price in model_prices.items():
                response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 5, "model": model}
                )
                responses[model] = response.json()
        
        amounts = {model: int(data["amount"]) for model, data in responses.items()}
        assert len(set(amounts.values())) == len(model_prices)
        
    @pytest.mark.asyncio
    async def test_pricing_api_error_returns_503(self, client, mock_mpp_config):
        with patch("main.get_fal_pricing", new_callable=AsyncMock) as mock_pricing:
            mock_pricing.return_value = (None, None)
            
            response = await client.post(
                "/api/video/generate",
                json={"prompt": "Test", "duration_seconds": 5}
            )
        
        assert response.status_code == 503
        data = response.json()
        assert data["success"] is False
        assert "pricing" in data["error"].lower() or "unable" in data["error"].lower()
        
    @pytest.mark.asyncio
    async def test_invalid_request_returns_400_before_challenge(self, client, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "", "duration_seconds": 5}
        )
        assert response.status_code == 400
        assert "WWW-Authenticate" not in response.headers
        
    @pytest.mark.asyncio
    async def test_missing_prompt_returns_400(self, client, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"duration_seconds": 5}
        )
        assert response.status_code == 400
        
    @pytest.mark.asyncio
    async def test_invalid_duration_returns_400(self, client, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 0}
        )
        assert response.status_code == 400
        
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 31}
        )
        assert response.status_code == 400
        
    @pytest.mark.asyncio
    async def test_invalid_model_returns_400(self, client, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5, "model": "invalid-model"}
        )
        assert response.status_code == 400
        
    @pytest.mark.asyncio
    async def test_challenge_expires_in_5_minutes(self, client, mock_fal_pricing, mock_mpp_config):
        from datetime import datetime, timezone, timedelta
        
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        
        header = response.headers["WWW-Authenticate"]
        expires_start = header.find('expires="') + len('expires="')
        expires_end = header.find('"', expires_start)
        expires_str = header[expires_start:expires_end]
        
        expires_at = datetime.fromisoformat(expires_str)
        now = datetime.now(timezone.utc)
        time_diff = (expires_at - now).total_seconds()
        
        assert 295 <= time_diff <= 305
        
    @pytest.mark.asyncio
    async def test_challenge_www_authenticate_format(self, client, mock_fal_pricing, mock_mpp_config):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        
        header = response.headers["WWW-Authenticate"]
        assert header.startswith('Payment ')
        
        parts = header.split(', ')
        assert len(parts) >= 6
        
        param_names = [part.split('=')[0] for part in parts]
        assert 'Payment realm' in param_names[0]
        assert 'id' in param_names[1]
        assert 'method' in param_names[2]
        assert 'intent' in param_names[3]
        assert 'request' in param_names[4]
        assert 'expires' in param_names[5]


class TestJobStatusEndpoint:
    @pytest.mark.asyncio
    async def test_get_job_status_not_found(self, client):
        job_id = str(uuid.uuid4())
        response = await client.get(f"/api/video/jobs/{job_id}")
        assert response.status_code == 404


class TestGalleryEndpoint:
    @pytest.mark.asyncio
    async def test_get_gallery_returns_empty_list(self, client):
        response = await client.get("/api/video/gallery")
        assert response.status_code == 200
        data = response.json()
        assert data["videos"] == []
        assert data["total"] == 0


class TestBroadcastIntegration:
    """Test fee sponsorship and broadcast integration."""
    
    @pytest.mark.asyncio
    async def test_successful_payment_includes_receipt_header(self, client, mock_fal_pricing, mock_submit_to_fal, mock_mpp_config):
        with patch("main.verify_transfer_calldata", return_value=(True, {}, "")):
            with patch("main.verify_transaction_signature", return_value=(True, "0x" + "00" * 40, "")):
                initial_response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test video", "duration_seconds": 3}
                )
                assert initial_response.status_code == 402
                session_id = initial_response.json()["session_id"]
                challenge = quote_sessions[session_id]["challenge"]
                
                from mpp.challenge import base64url_encode, jcs_encode
                
                credential_data = {
                    "challenge": challenge,
                    "payload": {
                        "transfer": {
                            "recipient": mock_mpp_config.TEMPO_SERVER_ADDRESS,
                            "amount": str(int(quote_sessions[session_id]["final_price_total"] * 1_000_000)),
                            "currency": "pathUSD"
                        },
                        "transaction_bytes": "0x" + "00" * 200
                    },
                    "type": "transaction"
                }
                
                credential_json = jcs_encode(credential_data)
                credential_b64 = base64url_encode(credential_json.encode('utf-8'))
                
                response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test video", "duration_seconds": 3},
                    headers={
                        "Authorization": f"Payment {credential_b64}",
                        "X-Session-ID": session_id
                    }
                )
                
                assert response.status_code == 200
                assert "Payment-Receipt" in response.headers
                
                receipt_header = response.headers["Payment-Receipt"]
                receipt = decode_receipt_header(receipt_header)
                
                assert receipt is not None
                assert receipt["method"] == "tempo"
                assert receipt["status"] == "success"
                assert "reference" in receipt
                assert receipt["reference"].startswith("0x")
                assert "timestamp" in receipt
                
    @pytest.mark.asyncio
    async def test_receipt_format_matches_spec(self, client, mock_fal_pricing, mock_submit_to_fal, mock_mpp_config):
        with patch("main.verify_transfer_calldata", return_value=(True, {}, "")):
            with patch("main.verify_transaction_signature", return_value=(True, "0x" + "00" * 40, "")):
                initial_response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 2}
                )
                session_id = initial_response.json()["session_id"]
                challenge = quote_sessions[session_id]["challenge"]
                
                from mpp.challenge import base64url_encode, jcs_encode
                
                credential_data = {
                    "challenge": challenge,
                    "payload": {
                        "transfer": {
                            "recipient": mock_mpp_config.TEMPO_SERVER_ADDRESS,
                            "amount": "1000000",
                            "currency": "pathUSD"
                        },
                        "transaction_bytes": "0x" + "00" * 200
                    },
                    "type": "transaction"
                }
                
                credential_json = jcs_encode(credential_data)
                credential_b64 = base64url_encode(credential_json.encode('utf-8'))
                
                response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 2},
                    headers={
                        "Authorization": f"Payment {credential_b64}",
                        "X-Session-ID": session_id
                    }
                )
                
                assert response.status_code == 200
                receipt_header = response.headers["Payment-Receipt"]
                receipt = decode_receipt_header(receipt_header)
                
                assert receipt is not None
                assert set(receipt.keys()) == {"method", "reference", "status", "timestamp"}
                assert receipt["method"] == "tempo"
                assert receipt["status"] == "success"
                
    @pytest.mark.asyncio
    async def test_job_stores_transaction_hash(self, client, mock_fal_pricing, mock_submit_to_fal, mock_mpp_config):
        with patch("main.verify_transfer_calldata", return_value=(True, {}, "")):
            with patch("main.verify_transaction_signature", return_value=(True, "0x" + "00" * 40, "")):
                initial_response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 2}
                )
                session_id = initial_response.json()["session_id"]
                challenge = quote_sessions[session_id]["challenge"]
                
                from mpp.challenge import base64url_encode, jcs_encode
                
                credential_data = {
                    "challenge": challenge,
                    "payload": {
                        "transfer": {
                            "recipient": mock_mpp_config.TEMPO_SERVER_ADDRESS,
                            "amount": "1000000",
                            "currency": "pathUSD"
                        },
                        "transaction_bytes": "0x" + "00" * 200
                    },
                    "type": "transaction"
                }
                
                credential_json = jcs_encode(credential_data)
                credential_b64 = base64url_encode(credential_json.encode('utf-8'))
                
                response = await client.post(
                    "/api/video/generate",
                    json={"prompt": "Test", "duration_seconds": 2},
                    headers={
                        "Authorization": f"Payment {credential_b64}",
                        "X-Session-ID": session_id
                    }
                )
                
                assert response.status_code == 200
                data = response.json()
                job_id = data["job_id"]
                
                assert job_id in jobs_db
                assert "transaction_hash" in jobs_db[job_id]
                assert jobs_db[job_id]["transaction_hash"].startswith("0x")


class TestBroadcastErrorHandling:
    """Test broadcast error handling."""
    
    @pytest.mark.asyncio
    async def test_missing_transaction_bytes_returns_402(self, client, mock_fal_pricing, mock_mpp_config):
        initial_response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 2}
        )
        session_id = initial_response.json()["session_id"]
        challenge = quote_sessions[session_id]["challenge"]
        
        from mpp.challenge import base64url_encode, jcs_encode
        
        credential_data = {
            "challenge": challenge,
            "payload": {
                "transfer": {
                    "recipient": mock_mpp_config.TEMPO_SERVER_ADDRESS,
                    "amount": "1000000",
                    "currency": "pathUSD"
                }
            },
            "type": "transaction"
        }
        
        credential_json = jcs_encode(credential_data)
        credential_b64 = base64url_encode(credential_json.encode('utf-8'))
        
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 2},
            headers={
                "Authorization": f"Payment {credential_b64}",
                "X-Session-ID": session_id
            }
        )
        
        assert response.status_code in [402, 200]


class TestReceiptGeneration:
    """Test receipt generation functions."""
    
    def test_create_receipt_format(self):
        tx_hash = "0x" + "ab" * 32
        receipt = create_receipt(tx_hash, "success")
        
        assert receipt["method"] == "tempo"
        assert receipt["reference"] == tx_hash
        assert receipt["status"] == "success"
        assert "timestamp" in receipt
        
    def test_format_receipt_header_encoding(self):
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
        
    def test_receipt_round_trip(self):
        receipt = {
            "method": "tempo",
            "reference": "0x" + "cd" * 32,
            "status": "success",
            "timestamp": "2025-01-15T12:00:00Z"
        }
        
        header = format_receipt_header(receipt)
        decoded = decode_receipt_header(header)
        
        assert decoded == receipt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
