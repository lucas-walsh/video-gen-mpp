"""
MPP RPC Client Interface

Abstract interface for blockchain RPC clients with mock implementation for testing.
Follows dependency injection pattern for easy swapping between mock and real implementations.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass


@dataclass
class RPCResponse:
    """JSON-RPC response structure."""
    jsonrpc: str = "2.0"
    id: Optional[Union[int, str]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error:
            result["error"] = self.error
        else:
            result["result"] = self.result
        return result
    
    @property
    def success(self) -> bool:
        """Check if response was successful."""
        return self.error is None


class RPCClientInterface(ABC):
    """
    Abstract interface for blockchain RPC clients.
    
    Implement this interface to create custom RPC clients
    that can be swapped with the mock implementation.
    """
    
    @abstractmethod
    async def call(self, method: str, params: List[Any]) -> RPCResponse:
        """
        Make an RPC call.
        
        Args:
            method: RPC method name
            params: Method parameters
            
        Returns:
            RPCResponse with result or error
        """
        pass
    
    @abstractmethod
    async def get_balance(
        self,
        address: str,
        block: str = "latest"
    ) -> int:
        """
        Get token balance for an address.
        
        Args:
            address: Account address
            block: Block number or tag
            
        Returns:
            Balance in smallest units (wei)
        """
        pass
    
    @abstractmethod
    async def send_raw_transaction(self, tx_bytes: str) -> str:
        """
        Broadcast a signed transaction.
        
        Args:
            tx_bytes: Hex-encoded signed transaction bytes
            
        Returns:
            Transaction hash
        """
        pass
    
    @abstractmethod
    async def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get transaction details by hash.
        
        Args:
            tx_hash: Transaction hash
            
        Returns:
            Transaction details or None if not found
        """
        pass
    
    @abstractmethod
    async def get_transaction_receipt(
        self,
        tx_hash: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get transaction receipt by hash.
        
        Args:
            tx_hash: Transaction hash
            
        Returns:
            Transaction receipt or None if not found
        """
        pass
    
    @abstractmethod
    async def get_chain_id(self) -> int:
        """
        Get chain ID.
        
        Returns:
            Chain ID as integer
        """
        pass
    
    @abstractmethod
    async def get_block_number(self) -> int:
        """
        Get current block number.
        
        Returns:
            Block number
        """
        pass


class MockRPCClient(RPCClientInterface):
    """
    Mock RPC client for testing.
    
    Simulates blockchain RPC calls without requiring actual network access.
    Maintains in-memory state for accounts and transactions.
    """
    
    def __init__(self, rpc_url: str = "https://rpc.testnet.tempo.xyz"):
        """
        Initialize mock RPC client.
        
        Args:
            rpc_url: RPC URL (stored for compatibility, not used in mock)
        """
        self.rpc_url = rpc_url
        self._balances: Dict[str, int] = {}
        self._transactions: Dict[str, Dict[str, Any]] = {}
        self._receipts: Dict[str, Dict[str, Any]] = {}
        self._block_number = 1000000
        self._chain_id = 57059
        self._nonces: Dict[str, int] = {}
        
        self._default_balance = 10 ** 18
        
    def set_balance(self, address: str, balance: int) -> None:
        """
        Set balance for an address.
        
        Args:
            address: Account address
            balance: Balance in smallest units
        """
        self._balances[address.lower()] = balance
    
    def set_transaction(self, tx_hash: str, tx_data: Dict[str, Any]) -> None:
        """
        Manually set a transaction for testing.
        
        Args:
            tx_hash: Transaction hash
            tx_data: Transaction data
        """
        self._transactions[tx_hash.lower()] = tx_data
    
    def set_receipt(self, tx_hash: str, receipt: Dict[str, Any]) -> None:
        """
        Manually set a transaction receipt for testing.
        
        Args:
            tx_hash: Transaction hash
            receipt: Transaction receipt
        """
        self._receipts[tx_hash.lower()] = receipt
    
    async def call(self, method: str, params: List[Any]) -> RPCResponse:
        """Make a mock RPC call."""
        handlers = {
            "eth_getBalance": self._handle_get_balance,
            "eth_sendRawTransaction": self._handle_send_raw_transaction,
            "eth_blockNumber": self._handle_block_number,
            "eth_chainId": self._handle_chain_id,
            "eth_getTransactionCount": self._handle_get_transaction_count,
            "eth_getTransactionByHash": self._handle_get_transaction_by_hash,
            "eth_getTransactionReceipt": self._handle_get_transaction_receipt,
            "eth_call": self._handle_eth_call,
            "eth_estimateGas": self._handle_estimate_gas,
            "eth_gasPrice": self._handle_gas_price,
            "eth_getCode": self._handle_get_code,
            "net_version": self._handle_net_version,
        }
        
        handler = handlers.get(method)
        if handler:
            try:
                result = await handler(params)
                return RPCResponse(result=result)
            except Exception as e:
                return RPCResponse(error={"code": -32000, "message": str(e)})
        else:
            return RPCResponse(
                error={"code": -32601, "message": f"Method {method} not found"}
            )
    
    async def get_balance(
        self,
        address: str,
        block: str = "latest"
    ) -> int:
        """Get balance for an address."""
        response = await self.call("eth_getBalance", [address, block])
        if response.error:
            raise ValueError(response.error["message"])
        return int(response.result, 16)
    
    async def send_raw_transaction(self, tx_bytes: str) -> str:
        """Broadcast a signed transaction."""
        response = await self.call("eth_sendRawTransaction", [tx_bytes])
        if response.error:
            raise ValueError(response.error["message"])
        return response.result
    
    async def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get transaction details."""
        response = await self.call("eth_getTransactionByHash", [tx_hash])
        return response.result
    
    async def get_transaction_receipt(
        self,
        tx_hash: str
    ) -> Optional[Dict[str, Any]]:
        """Get transaction receipt."""
        response = await self.call("eth_getTransactionReceipt", [tx_hash])
        return response.result
    
    async def get_chain_id(self) -> int:
        """Get chain ID."""
        response = await self.call("eth_chainId", [])
        if response.error:
            raise ValueError(response.error["message"])
        return int(response.result, 16)
    
    async def get_block_number(self) -> int:
        """Get current block number."""
        response = await self.call("eth_blockNumber", [])
        if response.error:
            raise ValueError(response.error["message"])
        return int(response.result, 16)
    
    async def _handle_get_balance(self, params: List[Any]) -> Any:
        """Handle eth_getBalance RPC call."""
        if not params or len(params) < 1:
            raise ValueError("Missing address parameter")
        
        address = params[0].lower()
        balance = self._balances.get(address, self._default_balance)
        return hex(balance)
    
    async def _handle_send_raw_transaction(self, params: List[Any]) -> Any:
        """Handle eth_sendRawTransaction RPC call."""
        if not params or len(params) < 1:
            raise ValueError("Missing transaction data")
        
        import hashlib
        import secrets
        
        tx_data = params[0]
        
        tx_hash = "0x" + secrets.token_hex(32)
        
        self._transactions[tx_hash.lower()] = {
            "hash": tx_hash,
            "from": "0x" + "0" * 40,
            "to": "0x" + "0" * 40,
            "value": hex(0),
            "input": tx_data,
            "blockNumber": hex(self._block_number),
        }
        
        self._receipts[tx_hash.lower()] = {
            "transactionHash": tx_hash,
            "transactionIndex": hex(0),
            "blockNumber": hex(self._block_number),
            "blockHash": "0x" + "0" * 64,
            "from": "0x" + "0" * 40,
            "to": "0x" + "0" * 40,
            "cumulativeGasUsed": hex(21000),
            "gasUsed": hex(21000),
            "status": hex(1),
            "logs": [],
        }
        
        return tx_hash
    
    async def _handle_block_number(self, params: List[Any]) -> Any:
        """Handle eth_blockNumber RPC call."""
        self._block_number += 1
        return hex(self._block_number)
    
    async def _handle_chain_id(self, params: List[Any]) -> Any:
        """Handle eth_chainId RPC call."""
        return hex(self._chain_id)
    
    async def _handle_get_transaction_count(self, params: List[Any]) -> Any:
        """Handle eth_getTransactionCount RPC call."""
        if not params:
            return hex(0)
        
        address = params[0].lower()
        nonce = self._nonces.get(address, 0)
        return hex(nonce)
    
    async def _handle_get_transaction_by_hash(self, params: List[Any]) -> Any:
        """Handle eth_getTransactionByHash RPC call."""
        if not params:
            raise ValueError("Missing transaction hash")
        
        tx_hash = params[0].lower()
        return self._transactions.get(tx_hash)
    
    async def _handle_get_transaction_receipt(self, params: List[Any]) -> Any:
        """Handle eth_getTransactionReceipt RPC call."""
        if not params:
            raise ValueError("Missing transaction hash")
        
        tx_hash = params[0].lower()
        return self._receipts.get(tx_hash)
    
    async def _handle_eth_call(self, params: List[Any]) -> Any:
        """Handle eth_call RPC call."""
        return "0x"
    
    async def _handle_estimate_gas(self, params: List[Any]) -> Any:
        """Handle eth_estimateGas RPC call."""
        return hex(21000)
    
    async def _handle_gas_price(self, params: List[Any]) -> Any:
        """Handle eth_gasPrice RPC call."""
        return hex(10 ** 9)
    
    async def _handle_get_code(self, params: List[Any]) -> Any:
        """Handle eth_getCode RPC call."""
        return "0x"
    
    async def _handle_net_version(self, params: List[Any]) -> Any:
        """Handle net_version RPC call."""
        return str(self._chain_id)
    
    def __repr__(self) -> str:
        return f"MockRPCClient(rpc_url={self.rpc_url})"
