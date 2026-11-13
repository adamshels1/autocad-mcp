# Install on Windows

The `autocad` MCP server for Claude: Claude draws in your running AutoCAD.

[Русская версия](INSTALL_WINDOWS.ru.md)

> The Windows version has so far been checked only by automated tests with a mocked AutoCAD. It has not been run on a real AutoCAD for Windows yet. Run the self-test from step 4 first and send its output if something fails.

## What you need

- **AutoCAD 2021 or newer, the full version.** AutoCAD LT will not work: it lacks the COM interface the server uses.
- **Claude Code or Claude Desktop** with a paid plan.
- **uv**, the Python package manager. You don't need to install Python, uv downloads it.

## 1. Install uv

In PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell, check: `uv --version`.

## 2. Download the project

With git:

```powershell
git clone https://github.com/adamshels1/autocad-mcp.git C:\cad-mcp\autocad
```

Or unpack the archive into `C:\cad-mcp\autocad`. It should contain the `server` and `lisp` folders. The `helper` folder is only for the Mac.

To update later: `cd C:\cad-mcp\autocad` and `git pull`, then `uv sync` in the `server` folder.

## 3. Install the dependencies

```powershell
cd C:\cad-mcp\autocad\server
uv sync
```

## 4. Self-test

Start AutoCAD, open or create a drawing, then:

```powershell
cd C:\cad-mcp\autocad\server
uv run autocad-mcp-selftest
```

You should see 10 `PASS` lines and `all 10 checks passed`. The self-test does not change the drawing. If there is a `FAIL`, send the whole output.

## 5. Connect to Claude

**Claude Desktop:** Settings → Desktop app → Extensions → Edit config (older versions: Settings → Developer → Edit Config), add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "autocad": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\cad-mcp\\autocad\\server", "autocad-mcp"]
    }
  }
}
```

**Claude Code:**

```powershell
claude mcp add autocad -s user -- uv run --directory C:\cad-mcp\autocad\server autocad-mcp
```

Restart Claude. The `autocad_*` tools show up in the tools list.

## 6. Try it in Claude

Write: «show the AutoCAD status», then «draw a floor plan of a 5×4 m room in AutoCAD».

## If it doesn't work

| What you see | What to do |
|---|---|
| `AutoCAD is not running (no COM object ...)` | AutoCAD is not running, or it is AutoCAD LT. Claude and AutoCAD must run as the same user with the same rights: if one runs «as administrator» and the other does not, they can't see each other. |
| `AutoCAD is busy` | A dialog is open or a command is running in AutoCAD. Press Esc in AutoCAD and try again. |
| `No drawing is open` | Open or create a drawing. |
| `No answer from AutoCAD within 60s` on the first call | AutoCAD asks whether to load a file from an untrusted folder. Allow it, or add `%USERPROFILE%\.cad-mcp\autocad` in Options → Files → Trusted Locations. |
| Question marks instead of Cyrillic letters | AutoCAD older than 2021. Update it or use Latin letters in layer names and texts. |
| `pywin32 is not installed` | Run `uv sync` in the `server` folder. |

Settings through environment variables (usually not needed):

- `AUTOCAD_PROGID`: another program on the AutoCAD platform, for example `BricscadApp.AcadApplication`. Not tested.
- `AUTOCAD_MCP_DIR`: the exchange folder, `%USERPROFILE%\.cad-mcp\autocad` by default.
