# Video Generation API with MPP Payments

AI video generation API (powered by FAL AI) that requires cryptographic micropayments on the Tempo blockchain via the Machine Payments Protocol (MPP).

## How it works

1. Client requests video generation, server responds with HTTP 402 and a payment challenge
2. Client signs a TIP-20 token transfer on Tempo and re-submits with the credential
3. Server verifies the payment, broadcasts the transaction, and dispatches the video job to FAL AI
4. Client polls for job status and retrieves the video URL on completion

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```env
# Required
FAL_AI_KEY=your_fal_ai_key
SERVER_PRIVATE_KEY=your_hex_private_key
MPP_SECRET_KEY=your_hmac_secret

# Optional (defaults shown)
TEMPO_RPC_URL=https://rpc.testnet.tempo.xyz
TEMPO_CHAIN_ID=57059
PATHUSD_ADDRESS=0x20c0000000000000000000000000000000000000
DEFAULT_VIDEO_MODEL=fal-ai/veo3.1/fast
HOST=0.0.0.0
PORT=8000
```

Generate secret keys:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Running the server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| POST | `/api/video/generate` | Request video generation (returns 402 challenge, or 200 with valid payment) |
| GET | `/api/video/jobs/{job_id}` | Poll job status |
| GET | `/api/video/gallery` | List videos |

## Client usage

The reference client handles the full payment flow:

```bash
export CLIENT_PRIVATE_KEY="0x..."

python client-pay.py \
  --prompt "A cat playing piano" \
  --duration 5 \
  --url http://localhost:8000
```

Options: `--model`, `--duration`, `--url`, `--private-key`, `-v` (verbose).

## Supported models

- `fal-ai/veo3.1/fast` (default)
- `fal-ai/veo3.1`
- `fal-ai/kling/video/v2.5/pro`
- `fal-ai/wan/v2.2-a14b/image-to-video`

## Testing

```bash
# Unit + integration tests
python -m pytest test_main.py test_mpp.py -v

# End-to-end tests (run standalone, not via pytest)
python test-full-flow.py

# Client tests
python -m pytest test_client_pay.py -v
```

## Project structure

```
main.py              # Starlette app, API routes, business logic
config.py            # App config (FAL, pricing, models)
client-pay.py        # Reference CLI payment client
mpp/
  config.py          # MPP/Tempo config and wallet setup
  challenge.py       # HMAC-bound challenge creation/verification
  credential.py      # Payment credential parsing and verification
  broadcast.py       # Transaction broadcast and receipt generation
  rpc.py             # RPC interface (mock implementation)
```

## Notes

- The blockchain RPC client is currently mocked (no real network calls)
- All state is in-memory and resets on restart
- Pricing is fetched from FAL AI's API with a 20% markup applied
- Payment challenges expire after 5 minutes
