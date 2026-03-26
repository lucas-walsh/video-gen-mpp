"""
MPP Configuration Module

Handles configuration for Machine Payments Protocol on Tempo Network.
Loads from environment variables with sensible defaults for testnet.
"""

import os
from typing import Optional
from eth_account import Account
from dotenv import load_dotenv

load_dotenv()


class MPPConfig:
    """Configuration for MPP on Tempo Network"""

    TEMPO_RPC_URL: str
    SERVER_PRIVATE_KEY: str
    SERVER_ADDRESS: str
    PATHUSD_ADDRESS: str
    MPP_SECRET_KEY: str
    CHAIN_ID: int

    def __init__(
        self,
        tempo_rpc_url: Optional[str] = None,
        server_private_key: Optional[str] = None,
        pathusd_address: Optional[str] = None,
        mpp_secret_key: Optional[str] = None,
        chain_id: Optional[int] = None,
    ):
        self.TEMPO_RPC_URL = tempo_rpc_url or os.getenv(
            "TEMPO_RPC_URL", "https://rpc.testnet.tempo.xyz"
        )

        self.SERVER_PRIVATE_KEY = server_private_key or os.getenv("SERVER_PRIVATE_KEY", "")

        self.PATHUSD_ADDRESS = pathusd_address or os.getenv(
            "PATHUSD_ADDRESS", "0x20c0000000000000000000000000000000000000"
        )

        self.MPP_SECRET_KEY = mpp_secret_key or os.getenv("MPP_SECRET_KEY", "")

        self.CHAIN_ID = chain_id or int(os.getenv("TEMPO_CHAIN_ID", "57059"))

        self._validate_config()
        self.SERVER_ADDRESS = self._derive_address()

    def _derive_address(self) -> str:
        """Derive Ethereum address from private key."""
        if not self.SERVER_PRIVATE_KEY:
            return ""

        key = self.SERVER_PRIVATE_KEY
        if key.startswith("0x"):
            key = key[2:]

        account = Account.from_key("0x" + key)
        return account.address

    def _validate_config(self) -> None:
        """Validate required configuration values."""
        if not self.TEMPO_RPC_URL:
            raise ValueError("TEMPO_RPC_URL is required")

        if not self.SERVER_PRIVATE_KEY:
            raise ValueError("SERVER_PRIVATE_KEY is required")

        if not self.MPP_SECRET_KEY:
            raise ValueError("MPP_SECRET_KEY is required")

        if not self.PATHUSD_ADDRESS:
            raise ValueError("PATHUSD_ADDRESS is required")

    def __repr__(self) -> str:
        return (
            f"MPPConfig("
            f"rpc_url={self.TEMPO_RPC_URL}, "
            f"address={self.SERVER_ADDRESS}, "
            f"pathusd={self.PATHUSD_ADDRESS}, "
            f"chain_id={self.CHAIN_ID})"
        )


_config: Optional[MPPConfig] = None


def get_config() -> MPPConfig:
    """Get or create global MPP configuration instance."""
    global _config
    if _config is None:
        _config = MPPConfig()
    return _config


def reset_config() -> None:
    """Reset global config (useful for testing)."""
    global _config
    _config = None


try:
    config = MPPConfig()
except ValueError:
    config = None
