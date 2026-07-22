# Contributing

Thanks for considering a contribution to EWIN Inbox.

## Development setup

Run any Odoo 18 (Community) instance with the module directories on its `addons_path`.
Install the core first, then the connector you are working on (the connector depends on
the core):

```bash
odoo -d <your-db> -i ewin_omnichannel_core,ewin_omnichannel_telegram --stop-after-init
```

Use `-u` instead of `-i` to upgrade modules you already installed after pulling changes.

## Running tests

Each module ships a `tests/` suite. Run one against a test database:

```bash
odoo -d <your-db> -u ewin_omnichannel_telegram --test-enable --stop-after-init \
  --http-port=8269 --test-tags /ewin_omnichannel_telegram
```

Notes:
- `--http-port=8269` avoids colliding with an already-running server on the default `8069`:
  Odoo's test runner still binds an HTTP port internally for controller/webhook tests. Any
  free port works.
- Provider API calls are mocked in tests — no real tokens or public webhook URL are needed
  to run the suite.
- A green run ends with `0 failed, 0 error(s) of N tests`.

## Coding conventions

- Follow the [Odoo coding guidelines](https://www.odoo.com/documentation/18.0/contributing/development/coding_guidelines.html)
  for naming, file layout, XML/Python style, and `ir.model.access.csv`/record-rule coverage
  for every new model.
- Odoo **model** technical names live in the `omnichannel.*` namespace (e.g.
  `omnichannel.conversation`); only the Odoo **module** names carry the `ewin_` prefix
  (`ewin_omnichannel_core`, `ewin_omnichannel_telegram`).
- `ewin_omnichannel_core` must stay **channel-agnostic**. It knows about
  `omnichannel.connector` (the abstract contract), the universal inbound message format,
  and generic account/conversation/message state — never about Telegram (or any other
  channel) specifics. Channel-specific fields, API clients, and webhook controllers belong
  in the connector module (`ewin_omnichannel_telegram` today, future connectors alongside
  it), which extends core models (`_inherit`) and implements `omnichannel.connector.<code>`.
- New channels should be addable as a new connector module depending only on
  `ewin_omnichannel_core`, without modifying core code.
- Keep secrets (tokens, webhook secrets) on admin-only fields, never write them into
  `omnichannel.error.log`, exceptions shown to non-admins, or log lines — see
  `SECURITY.md` for the pattern already in place for the Telegram token.
- Add or update tests alongside any behavior change; see `## Running tests` above.

## Branch / PR flow

1. Create a feature branch off `main` (e.g. `feat/short-description` or
   `fix/short-description`).
2. Make your changes, keeping commits focused and descriptive.
3. Ensure the full test suite passes (see above) before opening a pull request.
4. Open a pull request describing the change and referencing any related issue.

## Code review

All changes are reviewed before merge. Please respond to review feedback promptly and keep
the diff scoped to the stated task.
