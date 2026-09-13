import argparse
import asyncio
import os
import sys

import asyncpg
from eth_abi import decode
from web3 import AsyncWeb3
from web3.providers import AsyncHTTPProvider

TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TOPIC_TRANSFER_SINGLE = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
TOPIC_TRANSFER_BATCH = "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"


def parse_args():
    parser = argparse.ArgumentParser(description="Indexer for wallet ERC20/ERC1155 history")
    parser.add_argument("--rpc", default=os.environ.get("POLYGON_RPC_URL", "").strip(), help="RPC URL")
    parser.add_argument(
        "--db",
        default=os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/polymarket_db"),
        help="Database DSN",
    )
    parser.add_argument(
        "--wallet",
        default=os.environ.get("TARGET_WALLET", "0x46b353667fd7d846af3bbeda6584b0e5b883d3de"),
        help="Target address",
    )
    parser.add_argument("--start-block", type=int, default=int(os.environ.get("START_BLOCK", "55000000")))
    parser.add_argument("--end-block", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("MAX_LOG_BLOCK_RANGE", "10000")))
    return parser.parse_args()


def pad_address(addr: str) -> str:
    return "0x" + addr.lower().removeprefix("0x").zfill(64)


def to_bytes(val) -> bytes:
    if isinstance(val, bytes):
        return val
    return bytes.fromhex(str(val).removeprefix("0x"))


def to_hex(val) -> str:
    if isinstance(val, bytes):
        return "0x" + val.hex()
    return str(val).lower()


def build_balance_calldata(token_type: str, token_id: int, wallet: str) -> str:
    addr_bytes = bytes.fromhex(wallet.removeprefix("0x")).rjust(32, b"\x00")
    if token_type == "ERC20":
        return "0x70a08231" + addr_bytes.hex()
    if token_type == "ERC1155":
        return "0x00fdd58e" + addr_bytes.hex() + token_id.to_bytes(32, "big").hex()
    raise ValueError(f"Unsupported token type: {token_type}")


async def get_logs_range(w3: AsyncWeb3, filter_params: dict, start_block: int, end_block: int, max_range: int):
    logs = []
    step = max_range
    curr_from = start_block

    while curr_from <= end_block:
        curr_to = min(curr_from + step - 1, end_block)
        try:
            params = {**filter_params, "fromBlock": curr_from, "toBlock": curr_to}
            res = await w3.eth.get_logs(params)
            if res:
                logs.extend(res)
            curr_from = curr_to + 1
            step = min(max_range, step * 2)
        except Exception as err:
            if step == 1:
                raise RuntimeError(f"RPC query failed at block {curr_from}") from err
            step = max(1, step // 2)
    return logs


async def init_db(conn: asyncpg.Connection):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_logs (
            block_number BIGINT NOT NULL,
            tx_hash TEXT NOT NULL,
            log_index INTEGER NOT NULL,
            contract_address TEXT NOT NULL,
            event_type TEXT NOT NULL,
            token_type TEXT NOT NULL,
            token_id NUMERIC(78, 0) NOT NULL,
            from_address TEXT NOT NULL,
            to_address TEXT NOT NULL,
            amount NUMERIC(78, 0) NOT NULL,
            PRIMARY KEY (tx_hash, log_index, token_id)
        );
        CREATE INDEX IF NOT EXISTS idx_wallet_logs_addr ON wallet_logs(from_address, to_address);
    """)


def parse_log(log):
    topics = [to_hex(t) for t in log["topics"]]
    if not topics:
        return []

    sig = topics[0]
    data_bytes = to_bytes(log["data"])

    if sig == TOPIC_TRANSFER and len(topics) == 3:
        token_type, event_type = "ERC20", "Transfer"
        from_a = "0x" + topics[1][-40:]
        to_a = "0x" + topics[2][-40:]
        ids = [0]
        amounts = [int.from_bytes(data_bytes, "big") if data_bytes else 0]

    elif sig == TOPIC_TRANSFER_SINGLE and len(topics) == 4:
        token_type, event_type = "ERC1155", "TransferSingle"
        from_a = "0x" + topics[2][-40:]
        to_a = "0x" + topics[3][-40:]
        tid, amt = decode(["uint256", "uint256"], data_bytes)
        ids, amounts = [tid], [amt]

    elif sig == TOPIC_TRANSFER_BATCH and len(topics) == 4:
        token_type, event_type = "ERC1155", "TransferBatch"
        from_a = "0x" + topics[2][-40:]
        to_a = "0x" + topics[3][-40:]
        ids, amounts = decode(["uint256[]", "uint256[]"], data_bytes)

    else:
        return []

    return [
        {
            "block_number": log["blockNumber"],
            "tx_hash": str(log["transactionHash"]),
            "log_index": log["logIndex"],
            "contract_address": str(log["address"]).lower(),
            "event_type": event_type,
            "token_type": token_type,
            "token_id": t_id,
            "from_address": from_a,
            "to_address": to_a,
            "amount": amt,
        }
        for t_id, amt in zip(ids, amounts)
    ]


async def run():
    args = parse_args()

    if not args.rpc or not args.rpc.startswith(("http://", "https://")):
        sys.exit("Error: Invalid or missing --rpc argument")

    w3 = AsyncWeb3(AsyncHTTPProvider(args.rpc))
    if not await w3.is_connected():
        sys.exit("Error: RPC connection failed")

    wallet = args.wallet.lower()
    padded = pad_address(wallet)
    start_b = args.start_block
    end_b = args.end_block if args.end_block is not None else await w3.eth.block_number

    if end_b < start_b:
        sys.exit("Error: end_block < start_block")

    queries = [
        {"topics": [TOPIC_TRANSFER, padded]},
        {"topics": [TOPIC_TRANSFER, None, padded]},
        {"topics": [TOPIC_TRANSFER_SINGLE, None, padded]},
        {"topics": [TOPIC_TRANSFER_SINGLE, None, None, padded]},
        {"topics": [TOPIC_TRANSFER_BATCH, None, padded]},
        {"topics": [TOPIC_TRANSFER_BATCH, None, None, padded]},
    ]

    fetched = []
    for q in queries:
        res = await get_logs_range(w3, q, start_b, end_b, args.batch_size)
        fetched.extend(res)

    unique_logs = sorted(
        {(str(x["transactionHash"]), x["logIndex"]): x for x in fetched}.values(),
        key=lambda x: (x["blockNumber"], x["logIndex"]),
    )

    pool = await asyncpg.create_pool(args.db)
    try:
        async with pool.acquire() as conn:
            await init_db(conn)
            parsed_rows = 0
            for item in unique_logs:
                for row in parse_log(item):
                    parsed_rows += 1
                    await conn.execute(
                        """
                        INSERT INTO wallet_logs (
                            block_number, tx_hash, log_index, contract_address,
                            event_type, token_type, token_id, from_address, to_address, amount
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        ON CONFLICT (tx_hash, log_index, token_id) DO NOTHING;
                    """,
                        row["block_number"],
                        row["tx_hash"],
                        row["log_index"],
                        row["contract_address"],
                        row["event_type"],
                        row["token_type"],
                        row["token_id"],
                        row["from_address"],
                        row["to_address"],
                        row["amount"],
                    )

            if unique_logs and parsed_rows == 0:
                raise RuntimeError(f"RPC returned {len(unique_logs)} logs, but none could be parsed")

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    contract_address,
                    token_type,
                    token_id,
                    SUM(CASE WHEN to_address = $1 THEN amount ELSE -amount END) as balance
                FROM wallet_logs
                WHERE from_address = $1 OR to_address = $1
                GROUP BY contract_address, token_type, token_id
                HAVING SUM(CASE WHEN to_address = $1 THEN amount ELSE -amount END) > 0;
            """,
                wallet,
            )

            for r in rows:
                calc_bal = int(r["balance"])
                cdata = build_balance_calldata(r["token_type"], int(r["token_id"]), wallet)
                raw_res = await w3.eth.call(
                    {"to": r["contract_address"], "data": cdata},
                    block_identifier=end_b,
                )
                onchain_bal = int.from_bytes(raw_res, "big")

                if calc_bal != onchain_bal:
                    raise RuntimeError(
                        f"Mismatch for {r['contract_address']}:{r['token_id']} - db={calc_bal}, chain={onchain_bal}"
                    )

                print(f"Contract: {r['contract_address']} | TokenID: {r['token_id']} | Balance: {calc_bal}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run())