# schwab-advisor

Typed Python client for the [Schwab Advisor Services](https://developer.schwab.com/)
API — the institutional API set for RIAs custodying at Schwab, not the retail
Trader API.

```bash
pip install schwab-advisor
```

## Quickstart

Credentials come from the environment (or pass them to `SchwabAuth`
directly):

| Variable | Meaning |
|---|---|
| `SCHWAB_CLIENT_ID` | OAuth client id |
| `SCHWAB_CLIENT_SECRET` | OAuth client secret |
| `SCHWAB_REDIRECT_URI` | Redirect URI (default `https://127.0.0.1`) |
| `SCHWAB_TOKEN_FILE` | Token store (default `~/.schwab_tokens.json`) |
| `SCHWAB_ENVIRONMENT` | `sandbox` (default) or `production` |

```python
from schwab_advisor import SchwabAdvisorClient

with SchwabAdvisorClient() as client:
    profiles = client.get_account_profiles(page_limit=25, show_account="Show")
    for p in profiles.profiles:
        print(p.formatted_account, p.account_title)

    balances = client.get_balance_detail(profiles.profiles[0].formatted_account)
    positions = client.get_positions_list([p.formatted_account for p in profiles.profiles[:5]])
```

Every response is a typed dataclass with a `raw_data` escape hatch, so a
field the models do not yet cover is still reachable.

## Coverage

Wrappers for the Advisor Services products, grouped by segment:

- **Accounts** — account profiles, Account Inquiry (master accounts,
  accounts, account owners), Client Inquiry, Profiles and account holders,
  Preferences & Authorizations, Address Changes, Account Synchronization
- **Portfolio** — Balances, Positions, Transactions, Cost Basis
  (realized/unrealized gain-loss, lots, preferences)
- **Move Money** — Standing Authorizations, ACH and wire transfers,
  Move Money Activity, tax-withholding elections
- **Documents & status** — Reports (statements, confirmations, tax
  documents, PDF retrieval), Document Preferences, Alerts, Status,
  Service Requests, Feature Enrollment
- **Trading** — order submission, cancel/replace, order status, blotter
  and allocation upload

Access is granted per API product *and per route* on your Schwab app, so
what you can actually call depends on your entitlements, not on this
library. A 401 carrying
`InvalidAPICallAsNoApiProductMatchFound` in the `www-authenticate` header
means the route is not attached to your app — not that your token is bad.

## Development

```bash
poetry install
poetry run python -m pytest
```

The suite is offline and hermetic — every HTTP call is mocked, so it runs
without credentials.

Two suites diff the models against Schwab's OpenAPI specifications to
catch under-parsing. Those specs are Schwab's to distribute, so they are
not vendored here; the suites skip unless you point at a directory
containing them:

```bash
SCHWAB_SPECS_DIR=/path/to/specs poetry run python -m pytest
```

## Status

Validated end to end against the Schwab sandbox across four rounds of
Schwab's own technical-validation scenarios. Model completeness is
enforced by a schema-coverage guard; `raw_data` is retained on every
model so drift never blocks a caller.

## License

Apache-2.0 — see [LICENSE](LICENSE).
