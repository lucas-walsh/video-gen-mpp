#!/bin/bash

# Step 1: Initial request (gets 402 with quote)
echo "=== Step 1: Get Quote (402) ==="
QUOTE_RESPONSE=$(curl -s -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A cat walking through a futuristic city at sunset", "duration_seconds": 5}')

echo "$QUOTE_RESPONSE" | python3 -m json.tool

# Extract session_id
SESSION_ID=$(echo "$QUOTE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")
echo ""
echo "Session ID: $SESSION_ID"
echo ""

# Step 2: Retry with payment credential
echo "=== Step 2: Submit with Payment (200) ==="
GENERATE_RESPONSE=$(curl -s -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Payment mock_credential_123" \
  -H "X-Session-ID: $SESSION_ID" \
  -d '{"prompt": "A cat walking through a futuristic city at sunset", "duration_seconds": 5}')

echo "$GENERATE_RESPONSE" | python3 -m json.tool

# Extract job_id
JOB_ID=$(echo "$GENERATE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['job_id'])")
echo ""
echo "Job ID: $JOB_ID"
echo ""

# Step 3: Poll for status (repeat until completed)
echo "=== Step 3: Poll for Status ==="
echo "Polling every 3 seconds (press Ctrl+C to stop)..."
echo ""

while true; do
  STATUS_RESPONSE=$(curl -s -X GET "http://localhost:8000/api/video/jobs/$JOB_ID")
  echo "[$(date '+%H:%M:%S')] $STATUS_RESPONSE" | python3 -m json.tool
  
  STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    echo ""
    echo "=== Job Complete! ==="
    break
  fi
  
  sleep 3
  echo ""
done
