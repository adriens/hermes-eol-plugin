"""Tool schemas — what the LLM sees."""

EOL_SEARCH = {
    "name": "eol_search",
    "description": (
        "Find the endoflife.date identifier of a product (e.g. 'postgres' -> "
        "'postgresql', 'node' -> 'nodejs', 'k8s' -> 'kubernetes'). Matches names, "
        "aliases, labels, categories and tags. Use it when eol_product or eol_check "
        "reports an unknown product, or to list products in a category "
        "(lang, os, database, framework, server-app, ...)."
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
        },
        "required": ["query"],
    },
}

EOL_PRODUCT = {
    "name": "eol_product",
    "description": (
        "Get the release cycles of a product with their release date, LTS flag, "
        "end of active support, end of life (security support) date, and latest "
        "patch version, from endoflife.date. Use this instead of answering from "
        "memory whenever the user asks which versions of something are supported, "
        "when a version goes end-of-life, or what the latest LTS is."
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
        "found in a Dockerfile, CI config or lockfile)."
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
            "items": {
                "type": "array",
                "description": "Several product/version pairs to check in one call (max 50)",
                "items": {
                    "type": "object",
                    "properties": {
                        "product": {"type": "string"},
                        "version": {"type": "string"},
                    },
                    "required": ["product", "version"],
                },
            },
            "warn_days": {
                "type": "integer",
                "description": "Flag versions reaching end-of-life within this many days (default 180)",
            },
        },
    },
}
