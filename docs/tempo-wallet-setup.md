# Tempo Testnet Wallet Setup

This guide walks through setting up two Tempo testnet wallets (one for the server, one for the client) and funding them with pathUSD tokens.

## Quick Start (automated)

The fastest way to set up wallets is the automated script:

```bash
python scripts/setup_wallets.py
```

This generates server + client wallets, funds them via the Moderato faucet, and writes `.env` / `.env.client` files. See below for the manual approach.

## Overview

You need two wallets:

| Wallet | Purpose | Needs pathUSD? | Needs native token? |
|--------|---------|----------------|---------------------|
| **Server** | Receives payments, sponsors tx fees | No (receives from clients) | Yes (pays gas for fee sponsorship) |
| **Client** | Signs and pays for video generation | Yes | No (fees sponsored by server) |

## 1. Generate wallet key pairs

You can generate Tempo-compatible wallets with Python. Each wallet is an Ethereum-style secp256k1 key pair.

```bash
pip install eth-account
```

```python
from eth_account import Account

# Generate server wallet
server_account = Account.create()
print(f"Server private key: {server_account.key.hex()}")
print(f"Server address:     {server_account.address}")

# Generate client wallet
client_account = Account.create()
print(f"Client private key: {client_account.key.hex()}")
print(f"Client address:     {client_account.address}")
```

Save both private keys securely. You will need them for the `.env` files.

Alternatively, you can use any EVM-compatible wallet (MetaMask, Rabby, etc.) to generate keys.

## 2. Configure MetaMask (optional)

If you prefer a browser wallet for managing tokens:

1. Open MetaMask and click the network selector
2. Click "Add network" then "Add a network manually"
3. Enter the following:

| Field | Value |
|-------|-------|
| Network Name | Tempo Testnet |
| RPC URL | `https://rpc.moderato.tempo.xyz` |
| Chain ID | `42431` |
| Currency Symbol | `TEMPO` |
| Block Explorer URL | `https://explore.tempo.xyz` |

4. Click "Save"

> **Note**: The block explorer URL above follows the standard convention for the Tempo testnet. If it doesn't work, check the [Tempo documentation](https://tempo.xyz/docs) for the current URL.

## 3. Fund wallets with testnet tokens

### Get native tokens (for the server wallet)

The server wallet needs a small amount of native TEMPO tokens to sponsor transaction fees.

The Moderato testnet faucet is an RPC method. Call `tempo_fundAddress` to receive 1M of each testnet stablecoin:

```bash
curl -s -X POST https://rpc.moderato.tempo.xyz \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tempo_fundAddress","params":["YOUR_ADDRESS"],"id":1}'
```

Or use the automated setup script: `python scripts/setup_wallets.py`

### Get pathUSD tokens (for the client wallet)

The client wallet needs pathUSD (TIP-20 stablecoin) to pay for video generation.

**pathUSD contract address**: `0x20c0000000000000000000000000000000000000`

The `tempo_fundAddress` RPC call (above) distributes testnet pathUSD along with other stablecoins. No separate step is needed.

### Add pathUSD to MetaMask (optional)

To see your pathUSD balance in MetaMask:

1. Switch to the Tempo Testnet network
2. Click "Import tokens"
3. Enter the token contract address: `0x20c0000000000000000000000000000000000000`
4. The token symbol (`pathUSD`) and decimals should auto-populate
5. Click "Next" then "Import"

## 4. Configure the project

Once you have both wallets funded, update the environment files:

**Server (`.env`)**:
```bash
# Paste the server wallet's private key (hex, without 0x prefix)
TEMPO_SERVER_PRIVATE_KEY=your_server_private_key_hex
```

**Client (`.env.client`)**:
```bash
# Paste the client wallet's private key (hex, without 0x prefix)
TEMPO_CLIENT_PRIVATE_KEY=your_client_private_key_hex
```

## 5. Verify connectivity

Check that the RPC endpoint is reachable and your wallets are funded:

```bash
# Check RPC connectivity
curl -s -X POST https://rpc.moderato.tempo.xyz \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' | python3 -m json.tool
```

Expected response:
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": "0xa5bf"
}
```

(`0xa5bf` = 42431 in decimal, confirming Tempo Moderato testnet)

```bash
# Check native balance (replace ADDRESS with your server wallet address)
curl -s -X POST https://rpc.moderato.tempo.xyz \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_getBalance","params":["ADDRESS","latest"],"id":1}' | python3 -m json.tool
```

## Quick reference

| Item | Value |
|------|-------|
| Chain ID | `42431` |
| RPC URL | `https://rpc.moderato.tempo.xyz` |
| pathUSD contract | `0x20c0000000000000000000000000000000000000` |
| Transaction type | `0x76` (Tempo custom) |
| Client signing domain | `0x76` |
| Fee payer signing domain | `0x78` |

## Troubleshooting

**"Invalid chain ID" errors**: Make sure both `.env` and `.env.client` have `TEMPO_CHAIN_ID=42431`.

**"Insufficient funds" errors**: Verify the client wallet has enough pathUSD for the requested video. Check balance via MetaMask or the RPC `eth_getBalance` call above.

**RPC connection failures**: The Tempo Moderato testnet RPC may have rate limits or occasional downtime. If `https://rpc.moderato.tempo.xyz` is unreachable, check the [Tempo status page](https://tempo.xyz) or Discord for alternative endpoints.
