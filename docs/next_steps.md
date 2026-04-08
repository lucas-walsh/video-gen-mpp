# Tempo Testnet Integration: Next Steps

## Current State

The MPP challenge/credential flow is fully implemented (HMAC challenge generation, credential parsing, replay prevention). However, all blockchain interactions are mocked:

- `mpp/rpc.py` -- only `MockRPCClient` exists (in-memory fake)
- `mpp/broadcast.py` -- fee sponsorship appends 65 zero bytes instead of a real signature
- `client-pay.py` -- transaction encoding falls back to `b""` for Tempo's custom `0x76` type
- `main.py:62` -- wires up `MockRPCClient()` as the global RPC client

## Steps

### 1. Real RPC Client

Replace `MockRPCClient` in `mpp/rpc.py` with an HTTP JSON-RPC client. The abstract interface `RPCClientInterface` already defines the contract (`call`, `get_balance`, `send_raw_transaction`, `get_transaction`, `get_transaction_receipt`, `get_chain_id`, `get_block_number`).

- Swap `MockRPCClient()` for the real client in `main.py:62`
- RPC endpoint: try both `https://rpc.testnet.tempo.xyz` and `https://rpc.moderato.tempo.xyz` (research suggests moderato may be correct)

### 2. TIP-76 Transaction Encoding (`0x76`)

`client-pay.py` can't build valid Tempo transactions. Need to implement real RLP encoding for the `0x76` type.

**Key details from research:**
- TIP-76 includes: `chain_id`, `nonce` (2D: time-based + sequence-based), `calls` (array of `[to, value, data]`), `feeToken` (TIP-20 address), `feePayer` (address), `gasLimit`, `maxFeePerGas`, `maxPriorityFeePerGas`, `signature`
- Check `tempoxyz/pytempo` on GitHub for a reference implementation
- Standard `web3.py` works for RPC calls but not for encoding `0x76` -- need Tempo-specific encoding or manual RLP construction

### 3. Real Fee Sponsorship (`0x78`)

Update `mpp/broadcast.py:91-144` to actually co-sign transactions.

**Workflow:**
1. Client creates `0x76` tx with `feePayer` set to the server's address
2. Client signs the transaction
3. Server takes the client's signed tx, creates a sponsorship envelope, and co-signs it
4. Combined transaction is broadcast to the network

### 4. End-to-End Test

- Client signs a pathUSD transfer tx (TIP-20, ERC-20 compatible for simple transfers)
- Server sponsors fees and broadcasts to testnet
- Verify on-chain

## Research Notes

- **Faucet**: RPC method, not a website: `tempo_fundAddress` via POST to the RPC endpoint
- **pathUSD address**: may be `0x20c0...001` (not `...000`) -- needs verification
- **TIP-20**: ERC-20 compatible for simple `transfer(address,uint256)` calls; has extended features (memos) not needed for MVP
- **SDKs**: `tempoxyz/pytempo` (Python), `tempoxyz/tempo` (TypeScript) on GitHub
- **Missing module**: `mpp/mocks.py` is imported by `tests/test-tempo-setup.py` but doesn't exist -- needs to be created or tests updated

## Environment Variables (already renamed)

- Server: `TEMPO_SERVER_PRIVATE_KEY` in `.env`
- Client: `TEMPO_CLIENT_PRIVATE_KEY` in `.env.client`
- Addresses are derived at runtime from private keys
