# eol — end-of-life checks for Hermes Agent

Ask Hermes *"is Python 3.9 still supported?"* and it answers from training data
that may be a year old. This plugin gives the agent live lifecycle data from
[endoflife.date](https://endoflife.date) — 480+ products: languages, operating
systems, databases, frameworks, cloud services — so support dates come from the
source, not from memory.

From the author of [geol](https://github.com/opt-nc/geol), the endoflife.date CLI.
This plugin calls the endoflife.date API directly: no binary to install, stdlib
only, no API key.

## Tools

| Tool | What it does |
|---|---|
| `eol_search` | Find a product's identifier from a name, alias, category or tag (`postgres` → `postgresql`, `k8s` → `kubernetes`). |
| `eol_product` | All release cycles of a product: release date, LTS, end of active support, end of life, latest patch. |
| `eol_check` | Check one or many `product`/`version` pairs: matching cycle, status (`supported`, `security-only`, `eol`, `unknown`), days until EOL, whether a newer patch exists, and what to upgrade to (the next LTS for an LTS line). |

Things to try:

```
Which Node.js versions are still supported?
Is Ubuntu 22.04 still getting security updates? Until when?
Check the base images and runtimes in this Dockerfile for end-of-life versions.
Our stack is Python 3.9.7, PostgreSQL 13, Kubernetes 1.30 — what needs upgrading first?
```

## Install

```bash
hermes plugins install https://github.com/adriens/hermes-eol-plugin
hermes plugins enable eol
```

Or for development:

```bash
git clone https://github.com/adriens/hermes-eol-plugin ~/.hermes/plugins/eol
hermes plugins enable eol
hermes plugins doctor ~/.hermes/plugins/eol --ci
```

## What it does on your machine (disclosure)

- **Network:** HTTPS GET requests to `https://endoflife.date/api/v1/` only, when
  one of the tools is called. The request carries the product name being looked
  up — never file contents, paths or other session data.
- **No credentials**, no environment variables, no settings.
- **No file reads or writes**, no shell commands, no background processes.
- Responses are cached in memory for 6 hours to stay polite to the API; nothing
  is persisted.
- No telemetry.

## Development

```bash
python3 -m unittest discover -s tests -v    # offline, HTTP is mocked
hermes plugins validate . --install-deps    # the check catalog CI runs
```

## Credits

Data: [endoflife.date](https://endoflife.date) (MIT), maintained by its
community. Please contribute product data there.

## License

MIT
