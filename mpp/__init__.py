"""
Machine Payments Protocol (MPP) implementation for Tempo blockchain.

This package provides MPP client functionality for accepting payments
via TIP-20 stablecoins on the Tempo network.
"""

from mpp.config import MPPConfig, get_config, reset_config, config
from mpp.rpc import RPCClientInterface, MockRPCClient, RPCResponse
from mpp import challenge
from mpp import credential

__all__ = [
    "MPPConfig",
    "get_config",
    "reset_config",
    "config",
    "RPCClientInterface",
    "MockRPCClient",
    "RPCResponse",
    "challenge",
    "credential",
]
__version__ = "0.2.0"
