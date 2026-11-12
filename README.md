# AutoCAD + Claude (MCP)

An MCP server that lets Claude draw in your running AutoCAD through AutoLISP. Works on macOS and Windows.

[Русская версия](README.ru.md)

| System | How commands reach AutoCAD | Tested |
|---|---|---|
| macOS | `helper/acadctl` types a line into the AutoCAD command line | yes: macOS 26, AutoCAD 2026 (R25.1) |
| Windows | AutoCAD COM interface (`PostCommand`), no keyboard | only by automated tests with a mocked COM |

Step-by-step install: [macOS](INSTALL_MAC.md), [Windows](INSTALL_WINDOWS.md).

## Quick start: Claude Desktop on a Mac

1. Get the server and build its helper:

   ```bash
   git clone https://github.com/adamshels1/autocad-mcp.git ~/autocad-mcp
   cd ~/autocad-mcp/helper && swiftc -O acadctl.swift -o acadctl
   cd ../server && uv sync
   ```

2. In Claude Desktop open **Settings → Developer → Edit Config** and add this to `claude_desktop_config.json`
   (replace `NAME` with your Mac user name):

   ```json
   {
     "mcpServers": {
       "autocad": {
         "command": "/Users/NAME/.local/bin/uv",
         "args": ["run", "--directory", "/Users/NAME/autocad-mcp/server", "autocad-mcp"]
       }
     }
   }
   ```

3. Restart Claude, open a drawing in AutoCAD and ask: «Draw a floor plan of a small house in AutoCAD».

Claude Code instead of Desktop: `claude mcp add autocad -s user -- uv run --directory ~/autocad-mcp/server autocad-mcp`.

## How it works

```
Claude ── MCP (stdio) ──> server/autocad_mcp/server.py        shared logic
                            │ 1. writes the request ~/.cad-mcp/autocad/req_<id>.lsp
                            │ 2. the backend asks AutoCAD to run (progn (load "…req_<id>.lsp"))
                            │      backend_mac.py  → helper/acadctl (Accessibility)
                            │      backend_win.py  → COM, AcadDocument.PostCommand
                            ▼
                  AutoCAD: lisp/mcp_lib.lsp, mcp:run executes the code
                            │ with error trapping, as one UNDO group
                            ▼
                  ~/.cad-mcp/autocad/res_<id>.json   ← the server waits for this file
                  + command line output → the "console" field
```

- The request code goes into a file; AutoCAD only gets a short `load` line, so the code can be any size.
- On the first call the server adds the exchange folder to `TRUSTEDPATHS`, otherwise `SECURELOAD` cancels the `load`.
- Command line output is read through Accessibility on a Mac and from the AutoCAD log file on Windows (`LOGFILEMODE=1`).
- On a Mac `acadctl` checks that the command line holds exactly the right text before pressing Enter. If you were
  typing at that moment and the text got mixed up, it types it again.

## Tools

| Tool | What it does |
|---|---|
| `autocad_status` | Is AutoCAD running, is a drawing open, which platform |
| `autocad_eval_lisp` | Any AutoLISP; returns the value (JSON) and the console output |
| `autocad_command` | One command: `["_.CIRCLE",[0,0],50]`, `null` = Enter |
| `autocad_drawing_info` | File, units, extents, object count, layers, blocks, styles |
| `autocad_list_layers` | Layers with their properties |
| `autocad_list_entities` | Objects with their main DXF data, filtered by type and layer |
| `autocad_get_entity` | Full `entget` by handle |
| `autocad_screenshot` | A screenshot of the AutoCAD window |
| `autocad_type` | Send any text to the command line |
| `autocad_new_drawing` | A new drawing from the default template |

## Permissions on a Mac

The app that runs Claude (Claude Desktop, Terminal and so on) needs two switches in System Settings → Privacy & Security:

- **Accessibility**: to type into AutoCAD and read its command line.
- **Screen & System Audio Recording**: for `autocad_screenshot` and the window title.

Optional environment variables:

- `AUTOCAD_MCP_RESTORE_FOCUS=0`: keep AutoCAD in front after a command.
- `ACAD_BUNDLE_ID`: another AutoCAD version, `com.autodesk.AutoCAD2026` by default.
- `AUTOCAD_MCP_DIR`: the exchange folder, `~/.cad-mcp/autocad` by default.

## Checks

```bash
cd server
uv run pytest                    # unit tests, no AutoCAD needed
uv run autocad-mcp-selftest      # 10 checks on a real AutoCAD with an open drawing
AUTOCAD_MCP_LIVE=1 uv run pytest tests/test_live.py   # the same in more detail
```

The self-test and live tests do not change the drawing. On a Mac, keep off the keyboard while they run: AutoCAD comes to the front.

## Limits

- A drawing has to be open in AutoCAD.
- Mac: the screen must be unlocked; AutoCAD comes to the front for a split second on each command.
- Code that waits for the user (`getpoint`, `entsel`, commands with clicks, dialogs) hangs and the call fails on a timeout.
  `autocad_type` with empty text and `enter=false` sends Escape.
- Windows: full AutoCAD only, not LT. Cyrillic text needs AutoCAD 2021 or newer.

## Debugging on a Mac by hand

```bash
helper/acadctl window                  # the window and its title
helper/acadctl history | tail -20      # what AutoCAD printed
helper/acadctl type '(princ "hi")'     # type a line
```
