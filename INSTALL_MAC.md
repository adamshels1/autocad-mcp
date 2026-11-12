# Install on macOS

The `autocad` MCP server for Claude: Claude draws in your running AutoCAD.

[Русская версия](INSTALL_MAC.ru.md)

Tested on macOS 26 and AutoCAD 2026 for Mac.

## What you need

- **AutoCAD for Mac 2026**, the full version. For another version see «Another AutoCAD version» at the end.
- **Claude Code or Claude Desktop** with a paid plan.
- **Xcode Command Line Tools**, to build a small helper program.
- **uv**, the Python package manager. You don't need to install Python yourself.

## 1. Install the tools

In Terminal:

```bash
xcode-select --install          # if it is already there, the command says so
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen Terminal. Check: `swiftc --version` and `uv --version`.

## 2. Download the project

```bash
git clone https://github.com/adamshels1/autocad-mcp.git ~/autocad-mcp
```

To update later: `cd ~/autocad-mcp && git pull`, then repeat step 3.

## 3. Build the helper and install the dependencies

```bash
cd ~/autocad-mcp/helper && swiftc -O acadctl.swift -o acadctl
cd ../server && uv sync
```

## 4. Grant permissions

System Settings → Privacy & Security. Turn on the app that runs Claude (Terminal, iTerm, Claude Desktop) in two lists:

- **Accessibility**: to type commands into AutoCAD and read its command line.
- **Screen & System Audio Recording**: for AutoCAD screenshots.

Restart that app after turning them on.

## 5. Self-test

Start AutoCAD and create or open a drawing (not the Start tab). Then, **without touching the keyboard** for about 20 seconds:

```bash
cd ~/autocad-mcp/server
uv run autocad-mcp-selftest
```

You should see 10 `PASS` lines and `all 10 checks passed`. AutoCAD will come to the front now and then, that is normal. The self-test does not change the drawing. If there is a `FAIL`, send the whole output.

## 6. Connect to Claude

**Claude Desktop:** Settings → Developer → Edit Config, add to `claude_desktop_config.json` (replace `NAME` with your Mac user name):

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

**Claude Code:**

```bash
claude mcp add autocad -s user -- uv run --directory ~/autocad-mcp/server autocad-mcp
```

Restart Claude. The `autocad_*` tools show up in the tools list.

## 7. Try it in Claude

Write: «show the AutoCAD status», then «draw a floor plan of a 5×4 m room in AutoCAD».

## How it behaves on a Mac

AutoCAD for Mac has no programming interface for outside control, so commands are typed into its command line:

- On each command AutoCAD comes to the front for a split second, then the focus goes back.
- The screen must be unlocked.
- Better not to type while Claude is drawing. If keystrokes do get into a command, the helper notices and types the line again.
- The AutoCAD command line must be visible. To show it: `Cmd+3` or the `COMMANDLINE` command.

## If it doesn't work

| What you see | What to do |
|---|---|
| `helper not built` | Step 3 was skipped: build `acadctl`. |
| `no Accessibility permission` | Step 4: turn on Accessibility and restart Terminal or Claude. |
| `AutoCAD (...) is not running` | AutoCAD is not running or you have another version, see below. |
| `No drawing is open` | The Start tab is open. Create or open a drawing. |
| `could not bring AutoCAD to the front` | The screen is locked or a system dialog is on top. |
| `AutoCAD command line not found` | The command line is hidden: turn it on. |
| `the AutoCAD command line did not accept the text` | Someone typed during input or the focus went to another AutoCAD field. Run the command again. |
| `screencapture failed` | Step 4: turn on Screen Recording. |

## Another AutoCAD version

The server looks for AutoCAD 2026. For another version give its identifier:

```bash
osascript -e 'id of app "AutoCAD 2025"'      # prints, for example, com.autodesk.AutoCAD2025
claude mcp add autocad -s user -e ACAD_BUNDLE_ID=com.autodesk.AutoCAD2025 -- uv run --directory ~/autocad-mcp/server autocad-mcp
```

In Claude Desktop put it in the config as `"env": {"ACAD_BUNDLE_ID": "com.autodesk.AutoCAD2025"}` next to `"args"`.

Other versions were not tested. AutoCAD LT for Mac is not supported: it has no AutoLISP.

Optional settings:

- `AUTOCAD_MCP_RESTORE_FOCUS=0`: keep AutoCAD in front after a command.
- `AUTOCAD_MCP_DIR`: the exchange folder, `~/.cad-mcp/autocad` by default.
