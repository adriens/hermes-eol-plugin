"""eol plugin — end-of-life lookups from endoflife.date."""

from . import schemas, tools


def register(ctx):
    ctx.register_tool(name="eol_search", toolset="eol",
                      schema=schemas.EOL_SEARCH, handler=tools.eol_search)
    ctx.register_tool(name="eol_product", toolset="eol",
                      schema=schemas.EOL_PRODUCT, handler=tools.eol_product)
    ctx.register_tool(name="eol_check", toolset="eol",
                      schema=schemas.EOL_CHECK, handler=tools.eol_check)
