"""Tool schemas — what the LLM sees."""

EOL_SEARCH = {
    "name": "eol_search",
    "description": (
        "Find the endoflife.date identifier of a product (e.g. 'postgres' -> "
        "'postgresql', 'node' -> 'nodejs', 'k8s' -> 'kubernetes'). Matches names, "
        "aliases, labels, categories and tags. Use it when eol_product or eol_check "
        "reports an unknown product, or to list products in a category "
        "(lang, os, database, framework, server-app, ...). With list, returns every "
        "category or tag name instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Product name, alias, category or tag to look for",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default 20)",
            },
            "list": {
                "type": "string",
                "enum": ["categories", "tags"],
                "description": "Instead of searching, list every category or tag name",
            },
        },
    },
}

EOL_PRODUCT = {
    "name": "eol_product",
    "description": (
        "Get the release cycles of a product with their release date, LTS flag, "
        "end of active support, end of life (security support) date, and latest "
        "patch version, from endoflife.date. Use this instead of answering from "
        "memory whenever the user asks which versions of something are supported, "
        "when a version goes end-of-life, or what the latest LTS is. Also returns "
        "the product's package identifiers (purl, cpe) as used in SBOMs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product": {
                "type": "string",
                "description": "Product identifier or alias (e.g. 'python', 'ubuntu', 'postgresql', 'nodejs')",
            },
            "max_releases": {
                "type": "integer",
                "description": "Maximum number of cycles to return, newest first (default 15)",
            },
            "include_eol": {
                "type": "boolean",
                "description": "Include cycles that are already end-of-life (default true)",
            },
        },
        "required": ["product"],
    },
}

EOL_CHECK = {
    "name": "eol_check",
    "description": (
        "Check whether specific versions are still supported. For each "
        "product/version pair, returns the matching release cycle, a status "
        "(supported, security-only, eol or unknown), the end-of-life date, days "
        "left, whether a newer patch exists, the newest maintained cycle to "
        "upgrade to, and every cycle still maintained (with its LTS flag and "
        "dates) — base upgrade advice on that list only. Pass one pair with "
        "product+version, or many at once with items (for example everything "
        "found in a Dockerfile, CI config, lockfile or SBOM). An item can be "
        "identified by a package URL (purl, e.g. 'pkg:pypi/django@4.2.1', as in "
        "CycloneDX/SPDX SBOMs) or a CPE instead of product. Pass date to check "
        "the status at another day (e.g. 'what will be EOL by 2027-06-01')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product": {
                "type": "string",
                "description": "Product identifier or alias (e.g. 'python')",
            },
            "version": {
                "type": "string",
                "description": "Version in use, full or cycle only (e.g. '3.9.7', '3.9', '22.04', 'v18.19.0')",
            },
            "purl": {
                "type": "string",
                "description": "Package URL instead of product; its @version is used when version is omitted",
            },
            "cpe": {
                "type": "string",
                "description": "CPE 2.3 or 2.2 name instead of product (e.g. 'cpe:2.3:a:python:python:3.9.7')",
            },
            "items": {
                "type": "array",
                "description": "Several items to check in one call (max 50)",
                "items": {
                    "type": "object",
                    "properties": {
                        "product": {"type": "string"},
                        "version": {"type": "string"},
                        "purl": {"type": "string"},
                        "cpe": {"type": "string"},
                    },
                },
            },
            "date": {
                "type": "string",
                "description": "Reference date YYYY-MM-DD for the status and days left (default today)",
            },
            "warn_days": {
                "type": "integer",
                "description": "Flag versions reaching end-of-life within this many days (default 180)",
            },
        },
    },
}

EOL_STACK_CHECK = {
    "name": "eol_stack_check",
    "description": (
        "Check a geol stack file (.geol.yaml, the format of the geol CLI) with "
        "the same rules as 'geol check --strict': each component gets OK, WARN "
        "(under 30 days left), EOL or ERROR; skip, manual_eol, lts_strategy "
        "(any | latest), lts_grace_days and always-latest are enforced, and "
        "passed is false when anything is EOL or violates a policy. Read the file "
        "first (read_file) and pass its text as content."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Full text of the .geol.yaml file",
            },
            "date": {
                "type": "string",
                "description": "Reference date YYYY-MM-DD (default today), like geol check --date",
            },
        },
        "required": ["content"],
    },
}

EOL_STACK_FILE = {
    "name": "eol_stack_file",
    "description": (
        "Generate the text of a geol stack file (.geol.yaml) from the components "
        "of a project, so its end-of-life status can be tracked with geol in CI. "
        "First find the versions actually in use (Dockerfile FROM lines, "
        ".nvmrc, .python-version, pyproject.toml, package.json engines, go.mod, "
        "CI images, ...), then pass them here. Every product is resolved to its "
        "endoflife.date id; unknown ones are kept with skip: true. This tool does "
        "not write anything: save the returned content with write_file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "Application name for the report"},
            "app_id": {"type": "string", "description": "Optional identifier (default: slug of app_name)"},
            "items": {
                "type": "array",
                "description": "Components in use (max 50)",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Display name, unique (default: product label)"},
                        "product": {"type": "string", "description": "Product name or alias"},
                        "purl": {"type": "string", "description": "Package URL instead of product"},
                        "cpe": {"type": "string", "description": "CPE instead of product"},
                        "version": {"type": "string", "description": "Version in use"},
                        "lts_strategy": {"type": "string", "enum": ["any", "latest"]},
                        "lts_grace_days": {"type": "integer"},
                        "always_latest": {"type": "boolean"},
                        "skip": {"type": "boolean"},
                    },
                },
            },
        },
        "required": ["app_name", "items"],
    },
}
