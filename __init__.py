"""eol plugin — end-of-life lookups from endoflife.date."""

from . import hints, schemas, tools


def register(ctx):
    ctx.register_tool(name="eol_search", toolset="eol",
                      schema=schemas.EOL_SEARCH, handler=tools.eol_search)
    ctx.register_tool(name="eol_product", toolset="eol",
                      schema=schemas.EOL_PRODUCT, handler=tools.eol_product)
    ctx.register_tool(name="eol_check", toolset="eol",
                      schema=schemas.EOL_CHECK, handler=tools.eol_check)
    ctx.register_tool(name="eol_stack_check", toolset="eol",
                      schema=schemas.EOL_STACK_CHECK, handler=tools.eol_stack_check)
    ctx.register_tool(name="eol_stack_file", toolset="eol",
                      schema=schemas.EOL_STACK_FILE, handler=tools.eol_stack_file)
    ctx.register_hook("pre_llm_call", hints.make_hook(ctx))
