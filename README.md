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
| `--start-block` | `START_BLOCK` | `55000000` |
| `--end-block` | none | latest Polygon block |
| `--batch-size` | `MAX_LOG_BLOCK_RANGE` | `10000` |

Example with an RPC provider that permits only five blocks per `eth_getLogs` request:

```bash
python3 sobes.py \
  --rpc "$POLYGON_RPC_URL" \
  --db "$DATABASE_URL" \
  --batch-size 5
```

For a complete historical scan, choose `--start-block` no later than the wallet's first relevant activity. The allowed batch size depends on the RPC provider's plan and limits.

## Output and verification

Transfer events are stored in `wallet_logs`. The final balances are printed as raw token amounts. Each positive balance is queried directly from its contract using `balanceOf` or `balanceOf(address,uint256)` and the script exits with an error if the calculated value differs from the on-chain value at `--end-block`.

The script processes ERC-20 `Transfer`, ERC-1155 `TransferSingle`, and ERC-1155 `TransferBatch` events involving the selected wallet.

## Security

Do not commit RPC URLs containing API keys, database passwords, local dumps, or generated secrets. Revoke any key that has been publicly exposed and create a replacement.
