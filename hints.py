"""pre_llm_call hint — points the model at the eol_* tools when a turn is about versions.

Plugin tools sit behind Hermes' tool search, where the model only sees a one-line
summary, so a model answering "should we upgrade?" from memory never looks for them.
This hook matches the user message against a keyword list (local regex: no network,
no file access) and, on a match, appends a short note to that turn only.
"""

import re

HINT = (
    "[eol plugin] This request involves software versions, upgrades or security "
    "fixes. Use the eol_* tools for real support and end-of-life dates instead of "
    "answering from memory (find them with tool search if they are not listed): "
    "eol_check for every product/version, purl or CPE in play (Dockerfile FROM "
    "lines, docker-compose images, .nvmrc, .python-version, requirements.txt, "
    "pyproject.toml, package.json engines, go.mod, CI runners, SBOM components), "
    "eol_stack_file and eol_stack_check for .geol.yaml stack files. Base upgrade "
    "targets on the maintained cycles these tools return; a branch past its end of "
    "life gets no more security fixes."
)

_KEYWORDS = re.compile(
    r"""
    \b(?:
        eol | end[\s-]of[\s-]life | lts | lifecycle | life[\s-]cycle
      | (?:still\s+)?supported | unsupported | support(?:ed)?\s+until | deprecat\w*
      | upgrad\w* | migrat\w* | outdated | obsolete | sunset
      | cve-\d{4}-\d+ | ghsa(?:-[0-9a-z]{4}){3} | @cve | @ghsa | @osv
      | vulnerab\w* | security\s+(?:fix|patch|update|advisory|advisories)
      | dockerfile | docker-compose | compose\.ya?ml | \.nvmrc | \.python-version
      | requirements\.txt | pyproject\.toml | package\.json | go\.mod | pom\.xml
      | lockfile | sbom | cyclonedx | spdx | purl | pkg:[a-z]+/
      | geol | \.geol\.ya?ml | stack\s+file | tech(?:nology)?\s+stack | base\s+image
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def wants_hint(message):
    return bool(message) and _KEYWORDS.search(message) is not None


def make_hook(ctx):
    """Build the pre_llm_call callback; the `context_hint` setting turns it off."""

    def _enabled():
        try:
            return ctx.get_config("context_hint", default=True) is not False
        except Exception:
            return True

    def pre_llm_call(user_message=None, **kwargs):
        try:
            if _enabled() and wants_hint(user_message if isinstance(user_message, str) else ""):
                return {"context": HINT}
        except Exception:
            pass  # a hint is never worth failing a turn
        return None

    return pre_llm_call
