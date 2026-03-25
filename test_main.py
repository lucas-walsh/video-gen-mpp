import pytest
import time
import uuid
import os
from unittest.mock import patch, AsyncMock, MagicMock

from httpx import AsyncClient
from main import app, quote_sessions, cleanup_expired_sessions, calculate_final_price, verify_payment_credential, get_fal_pricing, jobs_db, last_poll_time, submit_to_fal, fetch_fal_job_status, fetch_fal_job_result
from config import MARKUP_PERCENT, QUOTE_TTL_SECONDS, SUPPORTED_VIDEO_MODELS, DEFAULT_VIDEO_MODEL


@pytest.fixture
async def client():
    quote_sessions.clear()
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
            "status_url": "https://queue.fal.run/fal-ai/veo3.1/fast/requests/req_test123/status"
        }
        yield mock


@pytest.fixture
def mock_submit_to_fal():
    with patch("main.submit_to_fal", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "request_id": "req_test123",
            "status": "IN_PROGRESS",
            "status_url": "https://queue.fal.run/fal-ai/veo3.1/fast/requests/req_test123/status"
        }
        yield mock


class TestHomepage:
    @pytest.mark.asyncio
    async def test_homepage_returns_api_info(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Video Generation API (MPP)"
        assert data["version"] == "1.0.0"
        assert "endpoints" in data
        assert "POST /api/video/generate" in data["endpoints"]
        assert "GET /api/video/jobs/{job_id}" in data["endpoints"]
        assert "GET /api/video/gallery" in data["endpoints"]


class TestVideoGenerationWithoutPayment:
    @pytest.mark.asyncio
    async def test_generate_without_payment_returns_402(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "A beautiful sunset", "duration_seconds": 5}
        )
        assert response.status_code == 402
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Payment required"
        assert "session_id" in data
        assert "pricing" in data
        assert "expires_in_seconds" in data
        assert data["pricing"]["duration_seconds"] == 5
        assert "WWW-Authenticate" in response.headers
        assert 'Payment realm="video-gen"' in response.headers["WWW-Authenticate"]

    @pytest.mark.asyncio
    async def test_402_response_includes_pricing_details(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test video", "duration_seconds": 10}
        )
        data = response.json()
        pricing = data["pricing"]
        assert "price_per_unit" in pricing
        assert pricing["price_per_unit"] == 0.05
        assert pricing["unit"] == "second"
        assert pricing["duration_seconds"] == 10
        assert pricing["subtotal_usd"] == 0.50
        assert pricing["markup_percent"] == MARKUP_PERCENT
        assert pricing["final_price_total"] == round(0.50 * (1 + MARKUP_PERCENT / 100), 2)


class TestVideoGenerationWithPayment:
    @pytest.mark.asyncio
    async def test_generate_with_valid_payment_returns_200(self, client, mock_fal_pricing, mock_submit_to_fal):
        initial_response = await client.post(
            "/api/video/generate",
            json={"prompt": "A cat playing piano", "duration_seconds": 3}
        )
        assert initial_response.status_code == 402
        session_id = initial_response.json()["session_id"]
        payment_credential = "test_credential_123"

        retry_response = await client.post(
            "/api/video/generate",
            json={"prompt": "A cat playing piano", "duration_seconds": 3},
            headers={
                "Authorization": f"Payment {payment_credential}",
                "X-Session-ID": session_id
            }
        )
        assert retry_response.status_code == 200
        data = retry_response.json()
        assert data["success"] is True
        assert "job_id" in data
        assert data["status"] == "processing"
        assert "cost_usd" in data
        assert "Payment-Receipt" in retry_response.headers
        assert session_id in retry_response.headers["Payment-Receipt"]

    @pytest.mark.asyncio
    async def test_session_cleared_after_successful_payment(self, client, mock_fal_pricing, mock_submit_to_fal):
        initial_response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 2}
        )
        session_id = initial_response.json()["session_id"]
        assert session_id in quote_sessions

        await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 2},
            headers={
                "Authorization": "Payment valid_cred",
                "X-Session-ID": session_id
            }
        )
        assert session_id not in quote_sessions


class TestInvalidPaymentCredential:
    @pytest.mark.asyncio
    async def test_invalid_session_id_returns_401(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5},
            headers={
                "Authorization": "Payment some_cred",
                "X-Session-ID": "nonexistent_session"
            }
        )
        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Invalid or expired payment credential"

    @pytest.mark.asyncio
    async def test_expired_session_returns_401(self, client, mock_fal_pricing):
        initial_response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        session_id = initial_response.json()["session_id"]
        quote_sessions[session_id]["expires_at"] = time.time() - 100

        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5},
            headers={
                "Authorization": "Payment some_cred",
                "X-Session-ID": session_id
            }
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_session_id_header_returns_402(self, client, mock_fal_pricing):
        initial_response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        session_id = initial_response.json()["session_id"]

        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5},
            headers={"Authorization": "Payment some_cred"}
        )
        assert response.status_code == 402

    @pytest.mark.asyncio
    async def test_empty_payment_credential_returns_402(self, client, mock_fal_pricing):
        initial_response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5}
        )
        session_id = initial_response.json()["session_id"]

        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5},
            headers={
                "Authorization": "Payment ",
                "X-Session-ID": session_id
            }
        )
        assert response.status_code == 402


class TestInvalidRequestBody:
    @pytest.mark.asyncio
    async def test_missing_prompt_returns_400(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"duration_seconds": 5}
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "prompt is required" in data["error"]

    @pytest.mark.asyncio
    async def test_missing_duration_returns_400(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "A test video"}
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "duration_seconds is required" in data["error"]

    @pytest.mark.asyncio
    async def test_duration_below_minimum_returns_400(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "A test video", "duration_seconds": 0}
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "duration_seconds must be between 1 and 30" in data["error"]

    @pytest.mark.asyncio
    async def test_duration_above_maximum_returns_400(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "A test video", "duration_seconds": 31}
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "duration_seconds must be between 1 and 30" in data["error"]

    @pytest.mark.asyncio
    async def test_empty_prompt_string_returns_400(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "", "duration_seconds": 5}
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "prompt must be a non-empty string" in data["error"]

    @pytest.mark.asyncio
    async def test_whitespace_only_prompt_returns_400(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "   ", "duration_seconds": 5}
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "prompt must be a non-empty string" in data["error"]

    @pytest.mark.asyncio
    async def test_non_numeric_duration_returns_400(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": "five"}
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False


class TestJobStatusEndpoint:
    @pytest.mark.asyncio
    async def test_get_job_status_returns_response(self, client):
        job_id = str(uuid.uuid4())
        response = await client.get(f"/api/video/jobs/{job_id}")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "Job not found"


class TestGalleryEndpoint:
    @pytest.mark.asyncio
    async def test_get_gallery_returns_empty_list(self, client):
        response = await client.get("/api/video/gallery")
        assert response.status_code == 200
        data = response.json()
        assert "videos" in data
        assert "total" in data
        assert data["videos"] == []
        assert data["total"] == 0


class TestQuoteSessionFlow:
    @pytest.mark.asyncio
    async def test_full_quote_session_flow(self, client, mock_fal_pricing, mock_submit_to_fal):
        response1 = await client.post(
            "/api/video/generate",
            json={"prompt": "Ocean waves", "duration_seconds": 8}
        )
        assert response1.status_code == 402
        session_id = response1.json()["session_id"]
        pricing = response1.json()["pricing"]

        assert session_id in quote_sessions
        assert quote_sessions[session_id]["prompt"] == "Ocean waves"
        assert quote_sessions[session_id]["duration_seconds"] == 8

        response2 = await client.post(
            "/api/video/generate",
            json={"prompt": "Ocean waves", "duration_seconds": 8},
            headers={
                "Authorization": "Payment valid_token",
                "X-Session-ID": session_id
            }
        )
        assert response2.status_code == 200
        assert response2.json()["success"] is True
        assert "job_id" in response2.json()
        assert session_id not in quote_sessions

    @pytest.mark.asyncio
    async def test_multiple_sessions_can_coexist(self, client, mock_fal_pricing):
        response1 = await client.post(
            "/api/video/generate",
            json={"prompt": "First video", "duration_seconds": 5}
        )
        response2 = await client.post(
            "/api/video/generate",
            json={"prompt": "Second video", "duration_seconds": 10}
        )

        session_id1 = response1.json()["session_id"]
        session_id2 = response2.json()["session_id"]

        assert session_id1 != session_id2
        assert session_id1 in quote_sessions
        assert session_id2 in quote_sessions
        assert quote_sessions[session_id1]["prompt"] == "First video"
        assert quote_sessions[session_id2]["prompt"] == "Second video"


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

    def test_cleanup_does_not_remove_valid_sessions(self):
        quote_sessions.clear()
        quote_sessions["session1"] = {
            "expires_at": time.time() + 300,
            "prompt": "test1"
        }
        quote_sessions["session2"] = {
            "expires_at": time.time() + 600,
            "prompt": "test2"
        }

        cleanup_expired_sessions()

        assert len(quote_sessions) == 2
        assert "session1" in quote_sessions
        assert "session2" in quote_sessions


class TestCalculateFinalPrice:
    def test_calculate_final_price_with_markup(self):
        fal_price = 1.00
        expected = 1.00 * (1 + MARKUP_PERCENT / 100)
        assert calculate_final_price(fal_price) == expected

    def test_calculate_final_price_zero_base(self):
        assert calculate_final_price(0.0) == 0.0

    def test_calculate_final_price_small_value(self):
        fal_price = 0.01
        expected = 0.01 * (1 + MARKUP_PERCENT / 100)
        assert calculate_final_price(fal_price) == expected


class TestVerifyPaymentCredential:
    def test_valid_credential_returns_true(self):
        quote_sessions.clear()
        session_id = "test_session"
        quote_sessions[session_id] = {
            "expires_at": time.time() + 300,
            "prompt": "test"
        }
        assert verify_payment_credential("valid_cred", session_id) is True

    def test_expired_session_returns_false(self):
        quote_sessions.clear()
        session_id = "expired_session"
        quote_sessions[session_id] = {
            "expires_at": time.time() - 100,
            "prompt": "test"
        }
        assert verify_payment_credential("cred", session_id) is False
        assert session_id not in quote_sessions

    def test_nonexistent_session_returns_false(self):
        assert verify_payment_credential("cred", "nonexistent") is False

    def test_empty_credential_returns_false(self):
        quote_sessions.clear()
        session_id = "test_session"
        quote_sessions[session_id] = {
            "expires_at": time.time() + 300,
            "prompt": "test"
        }
        assert verify_payment_credential("", session_id) is False


class TestFalPricingAPIMocking:
    @pytest.mark.asyncio
    async def test_get_fal_pricing_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "prices": [
                {"endpoint_id": "fal-ai/veo3.1/fast", "unit_price": 0.08, "unit": "second"}
            ]
        }

        async def mock_get(*args, **kwargs):
            return mock_response

        mock_client = MagicMock()
        mock_client.get = mock_get

        async def async_enter(self):
            return mock_client
        async def async_exit(self, *args):
            pass

        type(mock_client).__aenter__ = async_enter
        type(mock_client).__aexit__ = async_exit

        with patch("httpx.AsyncClient", return_value=mock_client):
            price, unit = await get_fal_pricing()
            assert price == 0.08
            assert unit == "second"

    @pytest.mark.asyncio
    async def test_get_fal_pricing_api_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        async def mock_get(*args, **kwargs):
            return mock_response

        mock_client = MagicMock()
        mock_client.get = mock_get

        async def async_enter(self):
            return mock_client
        async def async_exit(self, *args):
            pass

        type(mock_client).__aenter__ = async_enter
        type(mock_client).__aexit__ = async_exit

        with patch("httpx.AsyncClient", return_value=mock_client):
            price, unit = await get_fal_pricing()
            assert price is None
            assert unit is None

    @pytest.mark.asyncio
    async def test_get_fal_pricing_exception(self):
        async def mock_get(*args, **kwargs):
            raise Exception("Connection error")

        mock_client = MagicMock()
        mock_client.get = mock_get

        async def async_enter(self):
            return mock_client
        async def async_exit(self, *args):
            pass

        type(mock_client).__aenter__ = async_enter
        type(mock_client).__aexit__ = async_exit

        with patch("httpx.AsyncClient", return_value=mock_client):
            price, unit = await get_fal_pricing()
            assert price is None
            assert unit is None

    @pytest.mark.asyncio
    async def test_get_fal_pricing_missing_unit_price(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "prices": [
                {"endpoint_id": "fal-ai/veo3.1/fast", "unit": "second"}
            ]
        }

        async def mock_get(*args, **kwargs):
            return mock_response

        mock_client = MagicMock()
        mock_client.get = mock_get

        async def async_enter(self):
            return mock_client
        async def async_exit(self, *args):
            pass

        type(mock_client).__aenter__ = async_enter
        type(mock_client).__aexit__ = async_exit

        with patch("httpx.AsyncClient", return_value=mock_client):
            price, unit = await get_fal_pricing()
            assert price is None
            assert unit == "second"

    @pytest.mark.asyncio
    async def test_get_fal_pricing_no_api_key(self):
        with patch("main.FAL_AI_KEY", ""):
            price, unit = await get_fal_pricing()
            assert price is None
            assert unit is None


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_boundary_duration_minimum(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 1}
        )
        assert response.status_code == 402
        assert response.json()["pricing"]["duration_seconds"] == 1

    @pytest.mark.asyncio
    async def test_boundary_duration_maximum(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 30}
        )
        assert response.status_code == 402
        assert response.json()["pricing"]["duration_seconds"] == 30

    @pytest.mark.asyncio
    async def test_float_duration_accepted(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5.5}
        )
        assert response.status_code == 402
        assert response.json()["pricing"]["duration_seconds"] == 5.5

    @pytest.mark.asyncio
    async def test_very_long_prompt_accepted(self, client, mock_fal_pricing):
        long_prompt = "A " * 1000
        response = await client.post(
            "/api/video/generate",
            json={"prompt": long_prompt, "duration_seconds": 5}
        )
        assert response.status_code == 402

    @pytest.mark.asyncio
    async def test_special_characters_in_prompt(self, client, mock_fal_pricing):
        special_prompt = "Test with special chars: !@#$%^&*()_+{}|:<>?"
        response = await client.post(
            "/api/video/generate",
            json={"prompt": special_prompt, "duration_seconds": 5}
        )
        assert response.status_code == 402

    @pytest.mark.asyncio
    async def test_unicode_in_prompt(self, client, mock_fal_pricing):
        unicode_prompt = "Test with unicode: éèê 中文 Россия"
        response = await client.post(
            "/api/video/generate",
            json={"prompt": unicode_prompt, "duration_seconds": 5}
        )
        assert response.status_code == 402

    @pytest.mark.asyncio
    async def test_payment_header_bearer_format_ignored(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "Test", "duration_seconds": 5},
            headers={"Authorization": "Bearer token123"}
        )
        assert response.status_code == 402
        data = response.json()
        assert "session_id" in data


class TestModelSelection:
    @pytest.mark.asyncio
    async def test_request_without_model_uses_default(self, client, mock_fal_pricing):
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "A beautiful sunset", "duration_seconds": 5}
        )
        assert response.status_code == 402
        data = response.json()
        pricing = data["pricing"]
        assert pricing["model"] == DEFAULT_VIDEO_MODEL
        assert pricing["price_per_unit"] == 0.05

    @pytest.mark.asyncio
    async def test_request_with_invalid_model_returns_400(self, client, mock_fal_pricing):
        invalid_model = "invalid-model-xyz"
        response = await client.post(
            "/api/video/generate",
            json={"prompt": "A beautiful sunset", "duration_seconds": 5, "model": invalid_model}
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "model" in data["error"].lower() or "supported" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_default_model_configurable_via_env(self, client, mock_fal_pricing):
        custom_default = "fal-ai/veo3.1"
        with patch("main.DEFAULT_VIDEO_MODEL", custom_default):
            response = await client.post(
                "/api/video/generate",
                json={"prompt": "A beautiful sunset", "duration_seconds": 5}
            )
            assert response.status_code == 402
            data = response.json()
            pricing = data["pricing"]
            assert pricing["model"] == custom_default


class TestFalAiVideoGeneration:
    @pytest.mark.asyncio
    async def test_submit_to_fal_api_called_after_payment(self, client, mock_fal_pricing):
        mock_fal_response = {
            "request_id": "req_test123",
            "status": "IN_PROGRESS",
            "status_url": "https://queue.fal.run/fal-ai/veo3.1/fast/requests/req_test123/status"
        }

        with patch("main.submit_to_fal", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = mock_fal_response

            initial_response = await client.post(
                "/api/video/generate",
                json={"prompt": "A cat playing piano", "duration_seconds": 3}
            )
            assert initial_response.status_code == 402
            session_id = initial_response.json()["session_id"]

            retry_response = await client.post(
                "/api/video/generate",
                json={"prompt": "A cat playing piano", "duration_seconds": 3},
                headers={
                    "Authorization": "Payment valid_cred",
                    "X-Session-ID": session_id
                }
            )
            assert retry_response.status_code == 200
            data = retry_response.json()
            assert data["success"] is True
            assert "job_id" in data
            assert data["status"] == "processing"

            mock_submit.assert_called_once_with("fal-ai/veo3.1/fast", "A cat playing piano")

    @pytest.mark.asyncio
    async def test_get_job_status_from_fal(self, client):
        jobs_db.clear()
        last_poll_time.clear()

        job_id = "job_test123"
        jobs_db[job_id] = {
            "job_id": job_id,
            "request_id": "req_test123",
            "endpoint_id": "fal-ai/veo3.1/fast",
            "prompt": "Test prompt",
            "status": "processing",
            "video_url": None,
            "created_at": "2026-03-24T12:00:00Z",
        }

        import fal_client
        mock_completed = fal_client.Completed(logs=[], metrics={})
        mock_status_response = {"status": mock_completed}
        mock_result_response = {
            "video": {
                "url": "https://example.com/video.mp4",
                "width": 832,
                "height": 480
            }
        }

        with patch("main.fetch_fal_job_status", new_callable=AsyncMock) as mock_status, \
             patch("main.fetch_fal_job_result", new_callable=AsyncMock) as mock_result:
            mock_status.return_value = mock_status_response
            mock_result.return_value = mock_result_response

            response = await client.get(f"/api/video/jobs/{job_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == job_id
            assert data["status"] == "completed"
            assert data["video_url"] == "https://example.com/video.mp4"
            assert data["width"] == 832
            assert data["height"] == 480

            mock_status.assert_called_once_with("fal-ai/veo3.1/fast", "req_test123")
            mock_result.assert_called_once_with("fal-ai/veo3.1/fast", "req_test123")

    @pytest.mark.asyncio
    async def test_get_job_status_cached(self, client):
        jobs_db.clear()
        last_poll_time.clear()

        job_id = "job_cached123"
        jobs_db[job_id] = {
            "job_id": job_id,
            "request_id": "req_cached123",
            "endpoint_id": "fal-ai/veo3.1/fast",
            "prompt": "Test prompt",
            "status": "processing",
            "video_url": None,
            "created_at": "2026-03-24T12:00:00Z",
        }
        import time
        last_poll_time[job_id] = time.time()

        with patch("main.fetch_fal_job_status", new_callable=AsyncMock) as mock_status, \
             patch("main.fetch_fal_job_result", new_callable=AsyncMock) as mock_result:
            response = await client.get(f"/api/video/jobs/{job_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "processing"
            assert data["video_url"] is None

            mock_status.assert_not_called()
            mock_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_job_completed_returns_video_url(self, client):
        jobs_db.clear()
        last_poll_time.clear()

        job_id = "job_video123"
        jobs_db[job_id] = {
            "job_id": job_id,
            "request_id": "req_video123",
            "endpoint_id": "fal-ai/veo3.1/fast",
            "prompt": "Test prompt",
            "status": "completed",
            "video_url": "https://example.com/video.mp4",
            "width": 832,
            "height": 480,
            "created_at": "2026-03-24T12:00:00Z",
        }

        response = await client.get(f"/api/video/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == "completed"
        assert data["video_url"] == "https://example.com/video.mp4"
        assert data["width"] == 832
        assert data["height"] == 480

    @pytest.mark.asyncio
    async def test_get_job_not_found_returns_404(self, client):
        response = await client.get("/api/video/jobs/nonexistent_job")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "Job not found"


class TestFalAiVideoGeneration:
    @pytest.mark.asyncio
    async def test_submit_to_fal_api_called_after_payment(self, client, mock_fal_pricing):
        mock_fal_response = {
            "request_id": "req_test123",
            "status": "IN_PROGRESS",
            "status_url": "https://queue.fal.run/fal-ai/veo3.1/fast/requests/req_test123/status"
        }

        with patch("main.submit_to_fal", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = mock_fal_response

            initial_response = await client.post(
                "/api/video/generate",
                json={"prompt": "A cat playing piano", "duration_seconds": 3}
            )
            assert initial_response.status_code == 402
            session_id = initial_response.json()["session_id"]

            retry_response = await client.post(
                "/api/video/generate",
                json={"prompt": "A cat playing piano", "duration_seconds": 3},
                headers={
                    "Authorization": "Payment valid_cred",
                    "X-Session-ID": session_id
                }
            )
            assert retry_response.status_code == 200
            data = retry_response.json()
            assert data["success"] is True
            assert "job_id" in data
            assert data["status"] == "processing"

            mock_submit.assert_called_once_with("fal-ai/veo3.1/fast", "A cat playing piano")

    @pytest.mark.asyncio
    async def test_get_job_status_from_fal(self, client):
        jobs_db.clear()
        last_poll_time.clear()

        job_id = "job_test123"
        jobs_db[job_id] = {
            "job_id": job_id,
            "request_id": "req_test123",
            "endpoint_id": "fal-ai/veo3.1/fast",
            "prompt": "Test prompt",
            "status": "processing",
            "video_url": None,
            "created_at": "2026-03-24T12:00:00Z",
        }

        import fal_client
        mock_completed = fal_client.Completed(logs=[], metrics={})
        mock_status_response = {"status": mock_completed}
        mock_result_response = {
            "video": {
                "url": "https://example.com/video.mp4",
                "width": 832,
                "height": 480
            }
        }

        with patch("main.fetch_fal_job_status", new_callable=AsyncMock) as mock_status, \
             patch("main.fetch_fal_job_result", new_callable=AsyncMock) as mock_result:
            mock_status.return_value = mock_status_response
            mock_result.return_value = mock_result_response

            response = await client.get(f"/api/video/jobs/{job_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == job_id
            assert data["status"] == "completed"
            assert data["video_url"] == "https://example.com/video.mp4"
            assert data["width"] == 832
            assert data["height"] == 480

            mock_status.assert_called_once_with("fal-ai/veo3.1/fast", "req_test123")
            mock_result.assert_called_once_with("fal-ai/veo3.1/fast", "req_test123")

    @pytest.mark.asyncio
    async def test_get_job_status_cached(self, client):
        jobs_db.clear()
        last_poll_time.clear()

        job_id = "job_cached123"
        jobs_db[job_id] = {
            "job_id": job_id,
            "request_id": "req_cached123",
            "endpoint_id": "fal-ai/veo3.1/fast",
            "prompt": "Test prompt",
            "status": "processing",
            "video_url": None,
            "created_at": "2026-03-24T12:00:00Z",
        }
        import time
        last_poll_time[job_id] = time.time()

        with patch("main.fetch_fal_job_status", new_callable=AsyncMock) as mock_status, \
             patch("main.fetch_fal_job_result", new_callable=AsyncMock) as mock_result:
            response = await client.get(f"/api/video/jobs/{job_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "processing"
            assert data["video_url"] is None

            mock_status.assert_not_called()
            mock_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_job_completed_returns_video_url(self, client):
        jobs_db.clear()
        last_poll_time.clear()

        job_id = "job_video123"
        jobs_db[job_id] = {
            "job_id": job_id,
            "request_id": "req_video123",
            "endpoint_id": "fal-ai/veo3.1/fast",
            "prompt": "Test prompt",
            "status": "completed",
            "video_url": "https://example.com/video.mp4",
            "width": 832,
            "height": 480,
            "created_at": "2026-03-24T12:00:00Z",
        }

        response = await client.get(f"/api/video/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == "completed"
        assert data["video_url"] == "https://example.com/video.mp4"
        assert data["width"] == 832
        assert data["height"] == 480

    @pytest.mark.asyncio
    async def test_get_job_not_found_returns_404(self, client):
        response = await client.get("/api/video/jobs/nonexistent_job")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "Job not found"
