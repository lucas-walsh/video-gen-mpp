import uuid
import time
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
import fal_client

from config import FAL_AI_KEY, MARKUP_PERCENT, QUOTE_TTL_SECONDS, DEFAULT_VIDEO_MODEL, SUPPORTED_VIDEO_MODELS
from mpp.config import get_config as get_mpp_config
from mpp.challenge import create_challenge, format_challenge_header, decode_challenge_request
from mpp.credential import (
    parse_authorization_header,
    verify_credential,
    verify_transfer_parameters,
    verify_transaction_signature,
    verify_transfer_calldata,
    extract_transaction_bytes,
    check_replay_prevention,
)
from mpp.broadcast import (
    add_fee_sponsorship,
    broadcast_transaction,
    create_receipt,
    format_receipt_header,
)
from mpp.rpc import MockRPCClient
from asyncio import Lock

os.environ["FAL_KEY"] = FAL_AI_KEY

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

revenue_tracker = {
    "total_pathusd_received": 0.0,
    "successful_payments": 0,
    "failed_payments": 0,
    "failed_fal_calls": 0,
}

revenue_tracker = {
    "total_pathusd_received": 0.0,
    "successful_payments": 0,
    "failed_payments": 0,
    "failed_fal_calls": 0,
}


quote_sessions = {}
jobs_db = {}
last_poll_time = {}
POLL_CACHE_SECONDS = 5
jobs_lock = Lock()
used_credentials = set()
rpc_client = MockRPCClient()


def cleanup_expired_sessions():
    now = time.time()
    expired = [sid for sid, data in quote_sessions.items() if data["expires_at"] < now]
    for sid in expired:
        del quote_sessions[sid]


def validate_generate_request(data):
    if "prompt" not in data:
        raise ValueError("prompt is required")
    if "duration_seconds" not in data:
        raise ValueError("duration_seconds is required")
    duration = data["duration_seconds"]
    if not isinstance(duration, (int, float)) or duration < 1 or duration > 30:
        raise ValueError("duration_seconds must be between 1 and 30")
    if not isinstance(data.get("prompt"), str) or not data["prompt"].strip():
        raise ValueError("prompt must be a non-empty string")
    model = data.get("model")
    if model is not None:
        if model not in SUPPORTED_VIDEO_MODELS:
            raise ValueError(f"model must be one of: {', '.join(SUPPORTED_VIDEO_MODELS)}")
    return data


async def get_fal_pricing(endpoint_id: str = "fal-ai/veo3.1/fast"):
    if not FAL_AI_KEY:
        return None, None
    
    if FAL_AI_KEY.startswith("test_"):
        logger.info("Using test pricing for test key")
        return 0.05, "second"
    
    url = "https://api.fal.ai/v1/models/pricing"
    headers = {"Authorization": f"Key {FAL_AI_KEY}"}
    params = {"endpoint_id": endpoint_id}
    
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, timeout=10.0)
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch pricing: HTTP {response.status_code}")
                return None, None
            
            data = response.json()
            
            prices = data.get("prices", [])
            if not prices:
                logger.error(f"No pricing information returned for endpoint: {endpoint_id}")
                return None, None
            
            price_info = next(
                (p for p in prices if p.get("endpoint_id") == endpoint_id),
                prices[0]
            )
            price = price_info.get("unit_price")
            unit = price_info.get("unit", "second")
            
            return price, unit
            
    except Exception as e:
        logger.error(f"Error fetching pricing from Fal.ai: {e}")
        return None, None


def calculate_final_price(fal_price: float) -> float:
    """Calculate final price with markup."""
    return fal_price * (1 + MARKUP_PERCENT / 100)


def log_revenue(amount: float, success: bool = True) -> None:
    """Track revenue and payment statistics."""
    if success:
        revenue_tracker["total_pathusd_received"] += amount
        revenue_tracker["successful_payments"] += 1
        logger.info(f"Revenue tracked: ${amount:.6f} USD | Total: ${revenue_tracker['total_pathusd_received']:.6f}")
    else:
        revenue_tracker["failed_payments"] += 1
        logger.warning(f"Payment failed: ${amount:.6f} USD")


def log_fal_call(model: str, status: str, error: Optional[str] = None) -> None:
    """Log FAL API calls for monitoring."""
    if error:
        logger.error(f"FAL API call failed: model={model}, status={status}, error={error}")
        revenue_tracker["failed_fal_calls"] += 1
    else:
        logger.info(f"FAL API call successful: model={model}, status={status}")


async def submit_to_fal(model: str, prompt: str):
    if FAL_AI_KEY.startswith("test_"):
        logger.info("Using mock Fal.ai submission for test key")
        return {"request_id": f"mock_req_{uuid.uuid4().hex[:12]}", "handle": None}
    
    try:
        handle = await fal_client.submit_async(
            model,
            arguments={"prompt": prompt}
        )
        return {"request_id": handle.request_id, "handle": handle}
    except fal_client.FalClientHTTPError as e:
        logger.error(f"FAL HTTP error: {e.status_code} - {e.message}")
        raise
    except fal_client.FalClientError as e:
        logger.error(f"FAL client error: {e}")
        raise
    except fal_client.FalClientError as e:
        logger.error(f"FAL client error: {e}")
        raise


async def fetch_fal_job_status(endpoint_id: str, request_id: str):
    try:
        status = await fal_client.status_async(endpoint_id, request_id=request_id)
        return {"status": status}
    except fal_client.FalClientHTTPError as e:
        logger.error(f"FAL HTTP error: {e.status_code} - {e.message}")
        raise
    except fal_client.FalClientError as e:
        logger.error(f"FAL client error: {e}")
        raise


async def fetch_fal_job_result(endpoint_id: str, request_id: str):
    try:
        result = await fal_client.result_async(endpoint_id, request_id=request_id)
        return result
    except fal_client.FalClientHTTPError as e:
        logger.error(f"FAL HTTP error: {e.status_code} - {e.message}")
        raise
    except fal_client.FalClientError as e:
        logger.error(f"FAL client error: {e}")
        raise


async def generate_video(request):
    cleanup_expired_sessions()

    auth_header = request.headers.get("Authorization", "")
    payment_credential_b64 = None
    session_id = None

    if auth_header.startswith("Payment "):
        parts = auth_header.split(" ", 1)
        if len(parts) == 2:
            payment_credential_b64 = parts[1].strip()
            session_id = request.headers.get("X-Session-ID")

    if payment_credential_b64 and session_id:
        logger.info(f"Payment attempt: session_id={session_id}")
        
        credential_data = parse_authorization_header(auth_header)
        if not credential_data:
            return JSONResponse({
                "success": False,
                "error": "Invalid payment credential format"
            }, status_code=402)
        
        if session_id not in quote_sessions:
            return JSONResponse({
                "success": False,
                "error": "Invalid or expired payment credential"
            }, status_code=401)
        
        session = quote_sessions[session_id]
        challenge = session.get("challenge")
        
        if not challenge:
            return JSONResponse({
                "success": False,
                "error": "Session missing challenge data"
            }, status_code=400)
        
        mpp_config = get_mpp_config()
        if not mpp_config:
            return JSONResponse({
                "success": False,
                "error": "Server configuration error"
            }, status_code=500)
        
        is_valid, credential, error = verify_credential(
            auth_header=auth_header,
            secret_key=mpp_config.MPP_SECRET_KEY,
            expected_realm="video-gen-api"
        )
        
        if not is_valid or credential is None:
            logger.warning(f"Payment verification failed: {error}")
            return JSONResponse({
                "success": False,
                "error": error
            }, status_code=401)
        
        transfer_result, transfer_error = verify_transfer_parameters(credential, challenge)
        if not transfer_result:
            logger.warning(f"Transfer parameter verification failed: {transfer_error}")
            return JSONResponse({
                "success": False,
                "error": transfer_error
            }, status_code=402)
        
        replay_valid, replay_error = check_replay_prevention(credential, used_credentials)
        if not replay_valid:
            logger.warning(f"Replay prevention check failed: {replay_error}")
            return JSONResponse({
                "success": False,
                "error": replay_error
            }, status_code=401)
        
        tx_bytes = extract_transaction_bytes(credential)
        if tx_bytes:
            request_params = decode_challenge_request(challenge)
            if request_params:
                expected_recipient = request_params.get('recipient', '')
                expected_amount = int(float(request_params.get('amount', '0')) * 10 ** 6)
                
                calldata_valid, decoded_calldata, calldata_error = verify_transfer_calldata(
                    tx_bytes=tx_bytes,
                    expected_recipient=expected_recipient,
                    expected_amount=expected_amount,
                    currency_address=mpp_config.PATHUSD_ADDRESS,
                )
                
                if not calldata_valid:
                    logger.warning(f"Calldata verification failed: {calldata_error}")
                    return JSONResponse({
                        "success": False,
                        "error": f"Transaction verification failed: {calldata_error}"
                    }, status_code=402)
                
                sig_valid, recovered_signer, sig_error = verify_transaction_signature(tx_bytes)
                
                if not sig_valid:
                    logger.warning(f"Signature verification failed: {sig_error}")
                    return JSONResponse({
                        "success": False,
                        "error": f"Signature verification failed: {sig_error}"
                    }, status_code=402)
                
                logger.info(f"Transaction signature verified: signer={recovered_signer}")
        
        if not tx_bytes:
            logger.warning("Transaction bytes missing - using mock transaction for testing")
            tx_hash = f"0x{uuid.uuid4().hex}"
            logger.info(f"Using mock transaction hash: {tx_hash}")
        else:
            mpp_config = get_mpp_config()
            fee_payer_key = mpp_config.SERVER_PRIVATE_KEY
            
            sponsored_tx, sponsorship_error = add_fee_sponsorship(tx_bytes, fee_payer_key)
            if sponsorship_error:
                logger.error(f"Fee sponsorship failed: {sponsorship_error}")
                return JSONResponse({
                    "success": False,
                    "error": f"Fee sponsorship failed: {sponsorship_error}"
                }, status_code=402)
            
            logger.info("Fee sponsorship added successfully (mocked)")
            
            if not sponsored_tx:
                logger.error("Sponsored transaction bytes missing")
                return JSONResponse({
                    "success": False,
                    "error": "Fee sponsorship failed to produce transaction"
                }, status_code=402)
            
            tx_hash, broadcast_error = await broadcast_transaction(sponsored_tx, rpc_client)
            if broadcast_error or not tx_hash:
                logger.error(f"Broadcast failed: {broadcast_error}")
                return JSONResponse({
                    "success": False,
                    "error": f"Transaction broadcast failed: {broadcast_error}"
                }, status_code=503)
            
            logger.info(f"Transaction broadcast successful: {tx_hash}")
        
        receipt = create_receipt(tx_hash, "success")
        receipt_header = format_receipt_header(receipt)
        
        credential_id = credential.get('id', str(uuid.uuid4()))
        used_credentials.add(credential_id)
        
        job_id = f"job_{uuid.uuid4().hex}"
        model = session["model"]
        prompt = session["prompt"]
        del quote_sessions[session_id]

        try:
            fal_response = await submit_to_fal(model, prompt)
            log_fal_call(model, "submitted")
        except fal_client.FalClientHTTPError as e:
            log_fal_call(model, "failed", f"HTTP {e.status_code} - {e.message}")
            used_credentials.discard(credential_id)
            return JSONResponse({
                "success": False,
                "error": f"Failed to submit video generation request: {e.message}",
            }, status_code=503)
        except fal_client.FalClientError as e:
            log_fal_call(model, "failed", str(e))
            used_credentials.discard(credential_id)
            return JSONResponse({
                "success": False,
                "error": f"Failed to submit video generation request: {str(e)}",
            }, status_code=503)

        jobs_db[job_id] = {
            "job_id": job_id,
            "request_id": fal_response["request_id"],
            "endpoint_id": model,
            "prompt": prompt,
            "status": "processing",
            "video_url": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payment_credential_id": credential_id,
            "transaction_hash": tx_hash,
        }

        log_revenue(session["final_price_total"], success=True)
        
        return JSONResponse({
            "success": True,
            "job_id": job_id,
            "status": "processing",
            "cost_usd": session["final_price_total"],
            "message": "Payment verified. Video generation started.",
        }, headers={"Payment-Receipt": receipt_header})

    try:
        data = await request.json()
        validate_generate_request(data)
    except (ValueError, Exception) as e:
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=400)

    model = data.get("model", DEFAULT_VIDEO_MODEL)
    fal_price, unit = await get_fal_pricing(model)
    if fal_price is None:
        logger.error("Failed to fetch pricing from Fal.ai - returning 503")
        return JSONResponse({
            "success": False,
            "error": "Unable to fetch pricing from Fal.ai",
            "details": {
                "endpoint_id": model,
                "possible_causes": [
                    "Invalid or missing FAL_AI_KEY",
                    "Fal.ai API is temporarily unavailable",
                    "Network connectivity issue",
                ],
            },
        }, status_code=503)

    duration = data["duration_seconds"]
    fal_total = fal_price * duration
    final_price_total = calculate_final_price(fal_total)

    session_id = f"quote_{uuid.uuid4().hex[:12]}"
    
    mpp_config = get_mpp_config()
    if not mpp_config:
        logger.error("MPP config not available")
        return JSONResponse({
            "success": False,
            "error": "Server configuration error"
        }, status_code=500)
    
    challenge = create_challenge(
        amount=final_price_total,
        recipient=mpp_config.SERVER_ADDRESS,
        realm="video-gen-api",
        method="tempo",
        currency="pathUSD",
        currency_address=mpp_config.PATHUSD_ADDRESS,
        expires_in=QUOTE_TTL_SECONDS,
        secret_key=mpp_config.MPP_SECRET_KEY,
    )
    
    quote_sessions[session_id] = {
        "prompt": data["prompt"],
        "duration_seconds": duration,
        "model": model,
        "fal_price_per_unit": fal_price,
        "unit": unit,
        "final_price_total": final_price_total,
        "expires_at": time.time() + QUOTE_TTL_SECONDS,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "challenge": challenge,
    }

    challenge_amount_cents = int(final_price_total * 1_000_000)
    
    logger.info(
        f"Challenge generated: amount={final_price_total:.6f} USD, "
        f"recipient={mpp_config.SERVER_ADDRESS}, "
        f"expires_in={QUOTE_TTL_SECONDS}s, session_id={session_id}"
    )

    response = JSONResponse({
        "type": "https://paymentauth.org/problems/payment-required",
        "title": "Payment Required",
        "status": 402,
        "detail": f"This resource requires payment of ${final_price_total:.2f} USD in pathUSD",
        "amount": str(challenge_amount_cents),
        "currency": mpp_config.PATHUSD_ADDRESS,
        "expires_in": QUOTE_TTL_SECONDS,
        "session_id": session_id,
    }, status_code=402)

    response.headers["WWW-Authenticate"] = format_challenge_header(challenge)
    response.headers["Cache-Control"] = "no-store"

    return response


async def get_job(request):
    job_id = request.path_params["job_id"]
    job = jobs_db.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    now = time.time()
    last_poll = last_poll_time.get(job_id, 0)

    if now - last_poll > POLL_CACHE_SECONDS and job["status"] != "completed":
        async with jobs_lock:
            if now - last_poll_time.get(job_id, 0) > POLL_CACHE_SECONDS:
                try:
                    status_data = await fetch_fal_job_status(job["endpoint_id"], job["request_id"])
                    status_obj = status_data["status"]
                    
                    if isinstance(status_obj, fal_client.Completed):
                        job["status"] = "completed"
                        result_data = await fetch_fal_job_result(job["endpoint_id"], job["request_id"])
                        job["video_url"] = result_data.get("video", {}).get("url")
                        job["width"] = result_data.get("video", {}).get("width")
                        job["height"] = result_data.get("video", {}).get("height")
                    elif isinstance(status_obj, fal_client.InProgress):
                        job["status"] = "processing"
                    elif isinstance(status_obj, fal_client.Queued):
                        job["status"] = "queued"
                    else:
                        job["status"] = str(status_obj).lower()
                    
                    last_poll_time[job_id] = now
                except fal_client.FalClientHTTPError as e:
                    logger.error(f"HTTP error from Fal.ai: {e.status_code} - {e.message}")
                    job["status"] = "failed"
                    job["error"] = f"Fal.ai API error: {e.status_code}"
                except fal_client.FalClientError as e:
                    logger.error(f"Failed to fetch job status from Fal.ai: {e}")
                    job["status"] = "failed"
                    job["error"] = f"FAL client error: {str(e)}"

    response_data = {
        "job_id": job["job_id"],
        "status": job["status"],
        "video_url": job.get("video_url"),
        "width": job.get("width"),
        "height": job.get("height"),
        "created_at": job["created_at"],
    }
    
    if job.get("error"):
        response_data["error"] = job["error"]
    
    return JSONResponse(response_data)


async def get_gallery(request):
    return JSONResponse({"videos": [], "total": 0})


async def homepage(request):
    return JSONResponse({
        "name": "Video Generation API (MPP)",
        "version": "1.0.0",
        "endpoints": [
            "POST /api/video/generate",
            "GET /api/video/jobs/{job_id}",
            "GET /api/video/gallery",
        ],
    })


routes = [
    Route("/", homepage),
    Route("/api/video/generate", generate_video, methods=["POST"]),
    Route("/api/video/jobs/{job_id}", get_job, methods=["GET"]),
    Route("/api/video/gallery", get_gallery, methods=["GET"]),
]

app = Starlette(routes=routes)
