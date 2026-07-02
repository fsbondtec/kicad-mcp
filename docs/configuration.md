# Configuration Guide

This guide explains how to configure the KiCad MCP Server to suit your environment and requirements.

## Configuration Methods

The KiCad MCP Server can be configured in two ways, depending on the setting:

1. **Environment Variables**: only `KICAD_SEARCH_PATHS` is read from the environment (or a `.env` file)
2. **`kicad-mcp-config.json` or code modifications**: `KICAD_USER_DIR` and `KICAD_APP_PATH` are read from `kicad-mcp-config.json` (auto-created on first run under Claude's "Claude Extensions Settings" folder), falling back to the platform defaults hardcoded in `kicad_mcp/config.py`. They are **not** environment variables.

## Core Configuration Options

### Project Paths

These settings control where the server looks for KiCad projects:

| Setting | How it's set | Description | Default Value | Example |
|---------|-------------|-------------|---------------|---------|
| `KICAD_USER_DIR` | `kicad-mcp-config.json` / `config.py` | The main KiCad user directory | `~/Documents/KiCad` (macOS)<br>`~/KiCad/9.0/projects` (Windows)<br>`~/KiCad` (Linux) | `~/Documents/KiCadProjects` |
| `KICAD_SEARCH_PATHS` | Environment variable | Additional directories to search for KiCad projects (comma-separated) | None | `~/pcb,~/Electronics,~/Projects/KiCad` |


### Application Paths

These settings control how the server locates KiCad:
| Setting | How it's set | Description | Default Value | Example |
|---------|-------------|-------------|---------------|---------|
| `KICAD_APP_PATH` | `kicad-mcp-config.json` / `config.py` | Path to the KiCad application | `/Applications/KiCad/KiCad.app` (macOS)<br>`C:/Program Files/KiCad/9.0/` (Windows)<br>`/usr/share/kicad` (Linux) | `C:/Program Files/KiCad/9.0` |



## Directory Structure and Project Discovery

The server automatically searches for KiCad projects in:

1. The **KiCad user directory** (`KICAD_USER_DIR`)
2. Any **additional search paths** specified in `KICAD_SEARCH_PATHS`
3. **Common project locations** (auto-detected, including `~/Documents/PCB`, `~/Electronics`, etc.)

Projects are identified by the `.kicad_pro` file extension. The server recursively searches all configured directories to find KiCad projects.

## Client Configuration

### Claude Desktop Configuration

To configure Claude Desktop to use the KiCad MCP Server:

1. Create or edit the configuration file:

   **macOS**:
   ```bash
   mkdir -p ~/Library/Application\ Support/Claude
   vim ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```

   **Windows**:
   ```
   mkdir -p %APPDATA%\Claude
   notepad %APPDATA%\Claude\claude_desktop_config.json
   ```

2. Add the server configuration:
   ```json
   {
       "mcpServers": {
           "kicad": {
               "command": "/ABSOLUTE/PATH/TO/YOUR/PROJECT/kicad-mcp/venv/bin/python",
               "args": [
                   "/ABSOLUTE/PATH/TO/YOUR/PROJECT/kicad-mcp/main.py"
               ]
           }
       }
   }
   ```

3. For Windows, use the appropriate path format:
   ```json
   {
       "mcpServers": {
           "kicad": {
               "command": "C:\\Path\\To\\Your\\Project\\kicad-mcp\\venv\\Scripts\\python.exe",
               "args": [
                   "C:\\Path\\To\\Your\\Project\\kicad-mcp\\main.py"
               ]
           }
       }
   }
   ```

### Environment Variables in Client Configuration

You can also set `KICAD_SEARCH_PATHS` directly in the client configuration (this is the only setting actually read from the environment - `KICAD_APP_PATH`/`KICAD_USER_DIR` must be set via `kicad-mcp-config.json` or `config.py` as described above):

```json
{
    "mcpServers": {
        "kicad": {
            "command": "/ABSOLUTE/PATH/TO/YOUR/PROJECT/kicad-mcp/venv/bin/python",
            "args": [
                "/ABSOLUTE/PATH/TO/YOUR/PROJECT/kicad-mcp/main.py"
            ],
            "env": {
                "KICAD_SEARCH_PATHS": "/custom/path1,/custom/path2"
            }
        }
    }
}
```

## Advanced Configuration

### Custom KiCad Extensions

If you need to modify the recognized KiCad file extensions, you can edit `kicad_mcp/config.py`:

```python
# File extensions
KICAD_EXTENSIONS = {
    "project": ".kicad_pro",
    "pcb": ".kicad_pcb",
    "schematic": ".kicad_sch",
    # Add or modify extensions as needed
}
```

### DRC History Configuration

The server stores DRC history to track changes over time. By default, history is stored in:

- macOS/Linux: `~/.kicad_mcp/drc_history/`
- Windows: `%APPDATA%\kicad_mcp\drc_history\`

You can modify this in `kicad_mcp/utils/drc_history.py` if needed.

## Platform-Specific Configuration

### macOS

On macOS, KiCad is typically installed in `/Applications/KiCad/KiCad.app`. If you have multiple versions or a non-standard installation, set `KICAD_APP_PATH` to your KiCad.app path in `kicad-mcp-config.json` (or `config.py`).

### Windows

On Windows, KiCad is typically installed in `C:\Program Files\KiCad\9.0\`. If you have a different installation location, set `KICAD_APP_PATH` accordingly in `kicad-mcp-config.json` (or `config.py`).

For `KICAD_SEARCH_PATHS` in the `.env` file on Windows, you can use either:
- Forward slashes: `KICAD_SEARCH_PATHS=C:/Users/Username/Documents/KiCad`
- Escaped backslashes: `KICAD_SEARCH_PATHS=C:\\Users\\Username\\Documents\\KiCad`

### Linux

On Linux, KiCad's location varies by distribution. Common paths include:
- `/usr/share/kicad`
- `/usr/local/share/kicad`
- `/opt/kicad`

Set `KICAD_APP_PATH` to the appropriate path in `kicad-mcp-config.json` (or `config.py`).

## Debugging Configuration Issues

If you're having configuration problems:

1. Run the server:
   ```bash
   python main.py
   ```

2. Verify environment variables are being loaded:
   ```bash
   python -c "import os; print(os.environ.get('KICAD_SEARCH_PATHS', 'Not set'))"
   ```

3. Try absolute paths to eliminate path resolution issues
