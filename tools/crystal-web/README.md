# Crystal web tools

> **Deprecated.** This Python-based tool set is no longer maintained. Use the
> enhanced native .NET version instead:
> [YELANDAOKONG/CrystalCode.Tools.Web](https://github.com/YELANDAOKONG/CrystalCode.Tools.Web).

This is a Crystal Code external tool set. It uses only the Python 3 standard
library and is loaded from `~/.crystal/tools/crystal-web/`.

## Tools

- `websearch`: calls the hosted Parallel or Exa MCP endpoint. Parallel is the
  default because its Search MCP supports anonymous use.
- `webfetch`: performs a direct HTTP GET and converts HTML to text or Markdown.

## Optional environment variables

- `CRYSTAL_WEBSEARCH_PROVIDER=exa|parallel` selects the search backend. Parallel
  is the default.
- `EXA_API_KEY` and `PARALLEL_API_KEY` are optional credentials.
- `CRYSTAL_EXA_MCP_URL` and `CRYSTAL_PARALLEL_MCP_URL` override endpoints for
  testing or a compatible private gateway.

The script never prints credential-bearing URLs or authorization headers.
