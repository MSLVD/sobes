import asyncio
import unittest

from eth_abi import encode

from sobes import (
    TOPIC_TRANSFER,
    TOPIC_TRANSFER_BATCH,
    TOPIC_TRANSFER_SINGLE,
    build_balance_calldata,
    get_logs_range,
    parse_log,
    pad_address,
)


TX_HASH = "0x" + "11" * 32
BLOCK_HASH = "0x" + "22" * 32
CONTRACT = "0x" + "33" * 20
WALLET = "0x" + "44" * 20
OTHER = "0x" + "55" * 20


def topic_address(address):
    return "0x" + address.removeprefix("0x").zfill(64)


def base_log(topics, data):
    return {
        "blockNumber": 1,
        "blockHash": BLOCK_HASH,
        "transactionHash": TX_HASH,
        "logIndex": 0,
        "address": CONTRACT,
        "topics": topics,
        "data": data,
    }


class ParseLogTests(unittest.TestCase):
    def test_erc20_transfer(self):
        log = base_log(
            [TOPIC_TRANSFER, topic_address(OTHER), topic_address(WALLET)],
            "0x" + (7).to_bytes(32, "big").hex(),
        )
        rows = parse_log(log)
        self.assertEqual(rows[0]["token_type"], "ERC20")
        self.assertEqual(rows[0]["amount"], 7)

    def test_erc721_transfer_is_ignored(self):
        log = base_log(
            [TOPIC_TRANSFER, topic_address(OTHER), topic_address(WALLET)],
            "0x",
        )
        self.assertEqual(parse_log(log), [])

    def test_erc1155_single_transfer(self):
        log = base_log(
            [
                TOPIC_TRANSFER_SINGLE,
                topic_address(OTHER),
                topic_address(OTHER),
                topic_address(WALLET),
            ],
            "0x" + encode(["uint256", "uint256"], [9, 3]).hex(),
        )
        rows = parse_log(log)
        self.assertEqual((rows[0]["token_id"], rows[0]["amount"]), (9, 3))

    def test_erc1155_batch_combines_duplicate_ids(self):
        log = base_log(
            [
                TOPIC_TRANSFER_BATCH,
                topic_address(OTHER),
                topic_address(OTHER),
                topic_address(WALLET),
            ],
            "0x" + encode(["uint256[]", "uint256[]"], [[1, 1, 2], [4, 5, 6]]).hex(),
        )
        rows = parse_log(log)
        self.assertEqual([(row["token_id"], row["amount"]) for row in rows], [(1, 9), (2, 6)])


class UtilityTests(unittest.TestCase):
    def test_pad_address_rejects_invalid_address(self):
        with self.assertRaises(ValueError):
            pad_address("0x1234")

    def test_balance_calldata(self):
        erc20 = build_balance_calldata("ERC20", 0, WALLET)
        erc1155 = build_balance_calldata("ERC1155", 9, WALLET)
        self.assertEqual(len(erc20), 2 + 8 + 64)
        self.assertEqual(len(erc1155), 2 + 8 + 64 + 64)
        self.assertTrue(erc20.startswith("0x70a08231"))
        self.assertTrue(erc1155.startswith("0x00fdd58e"))


class RangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_range_adapts_to_provider_limit(self):
        class LimitedRpc:
            def __init__(self):
                self.accepted = []

            class Eth:
                def __init__(self, outer):
                    self.outer = outer

                async def get_logs(self, params):
                    size = params["toBlock"] - params["fromBlock"] + 1
                    if size > 10:
                        raise RuntimeError("provider range limit")
                    self.outer.accepted.append(size)
                    return []

            @property
            def eth(self):
                return self.Eth(self)

        rpc = LimitedRpc()
        await get_logs_range(rpc, {}, 0, 29, 50000)
        self.assertEqual(rpc.accepted, [6, 5, 10, 9])


if __name__ == "__main__":
    unittest.main()
