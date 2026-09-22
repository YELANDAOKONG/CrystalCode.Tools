# Crystal Code Tools

A collection of external tool sets for
[Crystal Code](https://github.com/YELANDAOKONG/CrystalCode). Each
tool set adds model-callable tools to the Plan and Work catalogs without
changing the host.

This repository is operator content only. It does not modify the Crystal
library or the Crystal Code host. The host owns discovery, catalog
registration, workspace fencing, approval, output truncation, and timeouts.

## Tool sets

| Set | Tools | Runner | Notes |
| :--- | :--- | :--- | :--- |
| [crystal-web](tools/crystal-web) | `websearch`, `webfetch` | exec | Python 3 standard library only |

## How Crystal Code finds these

Crystal Code scans one directory per tool set:

```text
~/.crystal/tools/<directory>/tools.json
<workspace>/.crystal/tools/<directory>/tools.json
```

The set identity is the directory name. A project directory of the same name
replaces the home set as a whole. Each set is one directory, one `tools.json`,
and one runner (`exec` or `dotnet`). `"enabled": false` in `tools.json` leaves
the directory in place without loading it.

Discovery is controlled by `/tools on|off|reload` in a session, or by setting
`"externalTools": false` in `~/.crystal/config.json`.

## Install a set

An `exec` set is copied as-is. Publish into the home or project tools directory:

```bash
mkdir -p ~/.crystal/tools
cp -r tools/crystal-web ~/.crystal/tools/crystal-web
```

Restart the session, or run `/tools reload`, to load the new set. A `dotnet`
set is published with `dotnet publish -c Release -o ~/.crystal/tools/<directory>`
so the directory contains `tools.json`, the assembly, and its `*.deps.json`.
See [external tools](https://github.com/YELANDAOKONG/CrystalCode/blob/master/docs/external-tools.md)
for the full manifest and publish layout.

## Catalogs and approval

A tool registers in Plan, Work, or both through its set-level or tool-level
`catalogs` field (default `["plan", "work"]`). Installing a set opts it into
the whole product unless the author narrows it. A `["work"]` set keeps Plan
free of its side effects.

Every external tool is at least Write + Workspace and goes through
`ToolInvocationPolicy` by default. `/tools` lists the effective catalog and
approval; `/tools home|project author|host` changes source trust.

## Adding a tool set

Create a new directory under `tools/`, give it a `tools.json`, and implement
the runner. The model-facing tool name comes from `tools[].name` (exec) or
`ITool.Definition.Name` (dotnet); it must not collide with a built-in name.
Set identity, manifest fields, and the dotnet load context are documented in
Crystal Code's
[docs/external-tools.md](https://github.com/YELANDAOKONG/CrystalCode/blob/master/docs/external-tools.md).

## Repository layout

```text
tools/
  crystal-web/
    tools.json            # set manifest
    crystal_web_tools.py  # exec runner
    README.md             # per-set notes
```

## License

MIT. See [LICENSE](LICENSE).
