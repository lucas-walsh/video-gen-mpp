#!/usr/bin/env python3
"""
Test script for Phase 1 MPP Implementation

Tests:
1. Config loading
2. Wallet derivation
3. Mock RPC calls
4. Spec compliance

Prints "Phase 1 OK" if all tests pass.
"""

import sys
import os

os.environ["TEMPO_SERVER_PRIVATE_KEY"] = "0x" + "01" * 32
os.environ["MPP_SECRET_KEY"] = "test-secret-key-for-hmac"
os.environ["TEMPO_RPC_URL"] = "https://rpc.moderato.tempo.xyz"
os.environ["PATHUSD_ADDRESS"] = "0x20c0000000000000000000000000000000000000"
os.environ["TEMPO_CHAIN_ID"] = "42431"


def print_section(title: str) -> None:
    """Print a formatted section header"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def test_config_loading() -> bool:
    """Test that config loads correctly"""
    print_section("Test 1: Config Loading")

    try:
        from mpp.config import MPPConfig, reset_config
        reset_config()

        print("✓ MPPConfig class imported")

        config = MPPConfig()
        print("✓ Config instance created")

        assert hasattr(config, "TEMPO_RPC_URL"), "Missing TEMPO_RPC_URL"
        print(f"  TEMPO_RPC_URL: {config.TEMPO_RPC_URL}")

        assert hasattr(config, "TEMPO_SERVER_PRIVATE_KEY"), "Missing TEMPO_SERVER_PRIVATE_KEY"
        pk_display = '***' + config.TEMPO_SERVER_PRIVATE_KEY[-4:] if config.TEMPO_SERVER_PRIVATE_KEY else 'NOT SET'
        print(f"  TEMPO_SERVER_PRIVATE_KEY: {pk_display}")

        assert hasattr(config, "PATHUSD_ADDRESS"), "Missing PATHUSD_ADDRESS"
        print(f"  PATHUSD_ADDRESS: {config.PATHUSD_ADDRESS}")

        assert hasattr(config, "MPP_SECRET_KEY"), "Missing MPP_SECRET_KEY"
        sk_display = '***' + config.MPP_SECRET_KEY[-4:] if config.MPP_SECRET_KEY else 'NOT SET'
        print(f"  MPP_SECRET_KEY: {sk_display}")

        assert hasattr(config, "CHAIN_ID"), "Missing CHAIN_ID"
        print(f"  CHAIN_ID: {config.CHAIN_ID}")

        print("\n✓ Config loading PASSED")
        return True

    except Exception as e:
        print(f"\n✗ Config loading FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_wallet_derivation() -> bool:
    """Test wallet address derivation from private key"""
    print_section("Test 2: Wallet Derivation")

    try:
        from mpp.config import MPPConfig, reset_config
        from eth_account import Account
        reset_config()

        config = MPPConfig()
        print(f"  Test Private Key: {config.TEMPO_SERVER_PRIVATE_KEY[:10]}...")
        print(f"  Derived Address: {config.TEMPO_TEMPO_SERVER_ADDRESS}")

        assert config.TEMPO_TEMPO_SERVER_ADDRESS.startswith("0x"), "Address should start with 0x"
        assert len(config.TEMPO_TEMPO_SERVER_ADDRESS) == 42, "Address should be 42 characters"

        expected_address = Account.from_key(config.TEMPO_SERVER_PRIVATE_KEY).address
        print(f"  Expected Address: {expected_address}")
        assert config.TEMPO_TEMPO_SERVER_ADDRESS == expected_address, "Account address should match"

        print("\n✓ Wallet derivation PASSED")
        return True

    except Exception as e:
        print(f"\n✗ Wallet derivation FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mock_rpc_client() -> bool:
    """Test mock RPC client functionality"""
    print_section("Test 3: Mock RPC Client")

    try:
        from mpp.mocks import MockTempoRPCClient
        from mpp.config import MPPConfig, reset_config
        reset_config()

        config = MPPConfig()
        client = MockTempoRPCClient()
        print("✓ MockTempoRPCClient instantiated")

        response = client.call("eth_getBalance", [config.TEMPO_TEMPO_SERVER_ADDRESS])
        print(f"  eth_getBalance result:")
        print(f"    Response: {response.result}")
        print(f"    Error: {response.error}")

        assert response.error is None, f"RPC call failed: {response.error}"
        assert response.result is not None, "No result from RPC call"
        assert isinstance(response.result, str), "Result should be hex string"
        assert response.result.startswith("0x"), "Result should be hex"

        balance = int(response.result, 16)
        assert balance > 0, f"Balance should be positive, got {balance}"
        print(f"    Balance: {balance} wei")

        print("\n✓ Mock RPC client PASSED")
        return True

    except Exception as e:
        print(f"\n✗ Mock RPC client FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mock_rpc_token_balance() -> bool:
    """Test mock RPC token balance query"""
    print_section("Test 4: Token Balance Query")

    try:
        from mpp.mocks import MockTempoRPCClient
        from mpp.config import MPPConfig, reset_config
        reset_config()

        config = MPPConfig()
        client = MockTempoRPCClient()

        pathusd_balance = client.get_token_balance(
            config.TEMPO_TEMPO_SERVER_ADDRESS,
            config.PATHUSD_ADDRESS
        )
        print(f"  pathUSD balance: {pathusd_balance}")

        assert pathusd_balance > 0, f"pathUSD balance should be positive"

        print("\n✓ Token balance query PASSED")
        return True

    except Exception as e:
        print(f"\n✗ Token balance query FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mock_rpc_send_transaction() -> bool:
    """Test mock RPC eth_sendRawTransaction call"""
    print_section("Test 5: Send Transaction")

    try:
        from mpp.mocks import MockTempoRPCClient
        from mpp.config import MPPConfig, reset_config
        reset_config()

        config = MPPConfig()
        client = MockTempoRPCClient()

        fake_tx = "0x" + "01" * 100
        response = client.call("eth_sendRawTransaction", [fake_tx])
        print(f"  eth_sendRawTransaction result:")
        print(f"    Hash: {response.result}")
        print(f"    Error: {response.error}")

        assert response.error is None, f"RPC call failed: {response.error}"
        assert response.result is not None, "No result from RPC call"
        assert response.result.startswith("0x"), "TX hash should be hex"
        assert len(response.result) == 66, f"TX hash length incorrect: {len(response.result)}"

        print("\n✓ Send transaction PASSED")
        return True

    except Exception as e:
        print(f"\n✗ Send transaction FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mock_rpc_chain_id() -> bool:
    """Test mock RPC eth_chainId call"""
    print_section("Test 6: Chain ID Query")

    try:
        from mpp.mocks import MockTempoRPCClient
        from mpp.config import MPPConfig, reset_config
        reset_config()

        config = MPPConfig()
        client = MockTempoRPCClient()

        response = client.call("eth_chainId", [])
        print(f"  eth_chainId result: {response.result}")

        assert response.error is None, f"RPC call failed: {response.error}"
        assert response.result is not None, "No result from RPC call"

        chain_id = int(response.result, 16)
        assert chain_id == 42431, f"Chain ID should be 42431, got {chain_id}"

        print("\n✓ Chain ID query PASSED")
        return True

    except Exception as e:
        print(f"\n✗ Chain ID query FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mock_set_balance() -> bool:
    """Test setting custom mock balances"""
    print_section("Test 7: Custom Mock Balances")

    try:
        from mpp.mocks import MockTempoRPCClient
        from mpp.config import MPPConfig, reset_config
        reset_config()

        config = MPPConfig()
        client = MockTempoRPCClient()

        custom_temp = 5 * 10 ** 18
        custom_pathusd = 500 * 10 ** 6

        client.set_balance(
            config.TEMPO_TEMPO_SERVER_ADDRESS,
            temp_balance=custom_temp,
            pathusd_balance=custom_pathusd
        )

        temp_balance = client.get_token_balance(config.TEMPO_TEMPO_SERVER_ADDRESS)
        pathusd_balance = client.get_token_balance(
            config.TEMPO_TEMPO_SERVER_ADDRESS,
            config.PATHUSD_ADDRESS
        )

        print(f"  Set TEMP balance: {custom_temp} wei, Got: {temp_balance} wei")
        print(f"  Set pathUSD balance: {custom_pathusd}, Got: {pathusd_balance}")

        assert temp_balance == custom_temp, \
            f"TEMP balance mismatch: expected {custom_temp}, got {temp_balance}"
        assert pathusd_balance == custom_pathusd, \
            f"pathUSD balance mismatch: expected {custom_pathusd}, got {pathusd_balance}"

        print("\n✓ Custom mock balances PASSED")
        return True

    except Exception as e:
        print(f"\n✗ Custom mock balances FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_spec_compliance() -> bool:
    """Test spec compliance for MPP"""
    print_section("Test 8: Spec Compliance")

    try:
        from mpp.config import MPPConfig, reset_config
        from mpp.mocks import MockTempoRPCClient
        reset_config()

        config = MPPConfig()

        print("Checking MPP spec requirements:")

        assert hasattr(config, "TEMPO_RPC_URL"), "Missing TEMPO_RPC_URL"
        print("  ✓ TEMPO_RPC_URL configured")

        assert hasattr(config, "TEMPO_SERVER_PRIVATE_KEY"), "Missing TEMPO_SERVER_PRIVATE_KEY"
        print("  ✓ TEMPO_SERVER_PRIVATE_KEY configured")

        assert hasattr(config, "TEMPO_SERVER_ADDRESS"), "Missing TEMPO_SERVER_ADDRESS"
        print("  ✓ TEMPO_SERVER_ADDRESS derived from private key")

        assert hasattr(config, "PATHUSD_ADDRESS"), "Missing PATHUSD_ADDRESS"
        print("  ✓ PATHUSD_ADDRESS configured (TIP-20 token)")

        assert hasattr(config, "MPP_SECRET_KEY"), "Missing MPP_SECRET_KEY"
        print("  ✓ MPP_SECRET_KEY configured (for HMAC)")

        client = MockTempoRPCClient()
        assert hasattr(client, "call"), "Missing call method"
        print("  ✓ RPC call method implemented")

        assert hasattr(client, "get_token_balance"), "Missing get_token_balance"
        print("  ✓ Token balance query implemented (TIP-20)")

        assert hasattr(client, "set_balance"), "Missing set_balance method"
        print("  ✓ Mock balance setting implemented")

        print("\n✓ Spec compliance PASSED")
        return True

    except Exception as e:
        print(f"\n✗ Spec compliance FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config_validation() -> bool:
    """Test that config validation works correctly"""
    print_section("Test 9: Config Validation")

    try:
        from mpp.config import MPPConfig
        import os

        old_key = os.environ.get("TEMPO_SERVER_PRIVATE_KEY", "")

        try:
            os.environ["TEMPO_SERVER_PRIVATE_KEY"] = ""

            try:
                config = MPPConfig(
                    tempo_rpc_url="http://test",
                    server_private_key="",
                    mpp_secret_key="test",
                    pathusd_address="0x" + "0" * 40
                )
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "TEMPO_SERVER_PRIVATE_KEY is required" in str(e)
                print(f"  ✓ Validation correctly rejects missing private key")

            os.environ["TEMPO_SERVER_PRIVATE_KEY"] = old_key

            print("\n✓ Config validation PASSED")
            return True

        finally:
            os.environ["TEMPO_SERVER_PRIVATE_KEY"] = old_key

    except Exception as e:
        print(f"\n✗ Config validation FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main() -> int:
    """Run all tests"""
    print("\n" + "=" * 60)
    print("  MPP Phase 1 Test Suite")
    print("  Testing: Config, Wallet, Mock RPC, Spec Compliance")
    print("=" * 60)

    tests = [
        ("Config Loading", test_config_loading),
        ("Wallet Derivation", test_wallet_derivation),
        ("Mock RPC Client", test_mock_rpc_client),
        ("Token Balance Query", test_mock_rpc_token_balance),
        ("Send Transaction", test_mock_rpc_send_transaction),
        ("Chain ID Query", test_mock_rpc_chain_id),
        ("Custom Mock Balances", test_mock_set_balance),
        ("Spec Compliance", test_spec_compliance),
        ("Config Validation", test_config_validation),
    ]

    results = []

    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n✗ {name} CRASHED: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print_section("Test Summary")

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {status}: {name}")

    print(f"\n  Total: {passed_count}/{total_count} tests passed")

    if passed_count == total_count:
        print("\n" + "=" * 60)
        print("  Phase 1 OK")
        print("=" * 60 + "\n")
        return 0
    else:
        print("\n" + "=" * 60)
        print("  Phase 1 FAILED")
        print("=" * 60 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
