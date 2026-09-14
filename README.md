# Polygon wallet history scanner

A small Python script that reads ERC-20 and ERC-1155 transfer events directly from a Polygon JSON-RPC endpoint, stores them in PostgreSQL, calculates wallet balances, and checks each result against the token contract at the selected block.

The script does not use Polymarket APIs or third-party indexers.

## Requirements

- Python 3.9 or newer
- PostgreSQL
- A Polygon mainnet JSON-RPC endpoint with `eth_getLogs` access

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Database

The database must already exist. The script creates the `wallet_logs` table and its address index on the first run.

Example PostgreSQL DSN:

```text
postgresql://postgres:postgres@127.0.0.1:5432/polymarket_db
```

## Run

Set the RPC endpoint and database DSN in the environment:

```bash
export POLYGON_RPC_URL='https://polygon-rpc.example/v2/your-key'
export DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/polymarket_db'
python3 sobes.py
```

The RPC URL and database credentials are intentionally not stored in the repository.

## Command-line options

All options can be provided as command-line arguments or through the corresponding environment variables.

| Option | Environment variable | Default |
| --- | --- | --- |
| `--rpc` | `POLYGON_RPC_URL` | empty |
| `--db` | `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/polymarket_db` |
| `--wallet` | `TARGET_WALLET` | `0x46b353667fd7d846af3bbeda6584b0e5b883d3de` |
| `--start-block` | `START_BLOCK` | `0` |
| `--end-block` | none | latest block minus confirmations |
| `--batch-size` | `MAX_LOG_BLOCK_RANGE` | `10` |
| `--confirmations` | `CONFIRMATIONS` | `64` |
| `--rpc-timeout` | `RPC_TIMEOUT_SECONDS` | `30` |

Example with an RPC provider that permits only five blocks per `eth_getLogs` request:

```bash
python3 sobes.py \
  --rpc "$POLYGON_RPC_URL" \
  --db "$DATABASE_URL" \
  --batch-size 5
```

For a complete historical scan, choose `--start-block` no later than the wallet's first relevant activity. The allowed batch size depends on the RPC provider's plan and limits.

The script requires Polygon mainnet (chain ID 137). Polygon's PoA block metadata is handled by the Web3 middleware. Unless `--end-block` is supplied, it scans to the latest block minus `--confirmations` and pins that block hash. It publishes new `wallet_logs` and `wallet_balances` snapshots only after all calculated token balances match `eth_call` and the MATIC balance is read at the same block; failed runs leave the previous snapshot intact.

## Output and verification

Transfer events are stored in `wallet_logs`. Verified balances are stored in `wallet_balances`, with MATIC represented by the zero address and token type `MATIC`. Positive final balances are printed as raw token amounts. Every aggregate found in the history is queried directly from its contract using `balanceOf` or `balanceOf(address,uint256)`, including zero balances, and the script exits with an error if the calculated value differs from the on-chain value at `--end-block`.

The script processes ERC-20 `Transfer`, ERC-1155 `TransferSingle`, and ERC-1155 `TransferBatch` events involving the selected wallet. ERC-721 `Transfer` events are ignored because they have the same topic but no ERC-20 amount data. It verifies every token aggregate found in the selected transfer history, including zero balances, against the contract at `--end-block`. A range with no supported token events still succeeds and records MATIC, but cannot discover a token whose entire history lies outside the selected range; use `--start-block 0` for complete event discovery.

## Tests

Run the standard-library regression suite and compile check:

```bash
python3 -m unittest discover -v
python3 -m py_compile sobes.py test_sobes.py
```

## Security

Do not commit RPC URLs containing API keys, database passwords, local dumps, or generated secrets. Revoke any key that has been publicly exposed and create a replacement.
