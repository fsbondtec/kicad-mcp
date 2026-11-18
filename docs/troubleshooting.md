# Troubleshooting Guide

This guide helps you troubleshoot common issues with the KiCad MCP Server.

## Server Setup Issues

### Server Not Starting

**Symptoms:**
- Error messages when running `python main.py`
- Server crashes immediately

**Possible Causes and Solutions:**

1. **Missing Dependencies**
   - **Error:** `ModuleNotFoundError: No module named 'mcp'`
   - **Solution:** Ensure you have installed the required packages, e.g. `uv sync` or `conda env create -f environment.yml` (see [README](../README.md#build))
   - **Error:** `ModuleNotFoundError: No module named 'prefab_ui'`
   - **Solution:** The SPICE simulation form needs `fastmcp` with its `apps` extra. Install the dependencies again from the current `pyproject.toml` / `environment.yml`, or add it with `pip install "fastmcp[apps]"`

2. **Python Version**
   - **Error:** Syntax errors or unsupported features
   - **Solution:** Verify you're using Python 3.10 or higher
     ```bash
     python --version
     ```

3. **Configuration Issues**
   - **Error:** `FileNotFoundError` or errors related to paths
   - **Solution:** Check your `.env` file and ensure all paths exist

4. **Permission Issues**
   - **Error:** `PermissionError: [Errno 13] Permission denied`
   - **Solution:** Ensure you have the necessary permissions for all directories and files

## MCP Client Integration Issues

### Server Not Appearing in Client

**Symptoms:**
- Server not showing in Claude Desktop tools dropdown
- Unable to access KiCad tools in the client

**Possible Causes and Solutions:**

1. **Configuration File Issues**
   - **Problem:** Incorrect or missing configuration
   - **Solution:** Check your client configuration file:
     
     For Claude Desktop (macOS):
     ```bash
     cat ~/Library/Application\ Support/Claude/claude_desktop_config.json
     ```
     
     For Claude Desktop (Windows):
     ```bash
     type %APPDATA%\Claude\claude_desktop_config.json
     ```
     
     Ensure it contains the correct server configuration:
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

2. **Working Directory Issues**
   - **Problem:** The server can't find files due to working directory issues
   - **Solution:** Always use absolute paths in your configuration
     
     Replace:
     ```json
     "args": ["main.py"]
     ```
     
     With:
     ```json
     "args": ["/absolute/path/to/main.py"]
     ```

3. **Client Needs Restart**
   - **Problem:** Changes to configuration not applied
   - **Solution:** Close and reopen your MCP client

4. **MCP Protocol Version Mismatch**
   - **Problem:** Client and server using incompatible protocol versions
   - **Solution:** Update both the client and server to compatible versions

## Working with KiCad

### KiCad Python Modules Not Found

**Symptoms:**
- Warning messages about missing KiCad Python modules

**Possible Causes and Solutions:**

1. **KiCad Not Installed**
   - **Problem:** KiCad installation not found
   - **Solution:** Install KiCad from [kicad.org](https://www.kicad.org/download/)

2. **Non-standard KiCad Installation**
   - **Problem:** KiCad installed in a non-standard location
   - **Solution:** Set `KICAD_APP_PATH` (`_DEFAULT_APP_PATH` in `kicad_mcp/config.py`) - it is **not** an environment variable and not read from `kicad-mcp-config.json`

3. **Python Path Issues**
   - **Problem:** KiCad Python modules not in Python path
   - **Solution:** Check server logs for Python path setup errors

## Project Discovery Issues

### KiCad Projects Not Found

**Symptoms:**
- No projects listed when asking for KiCad projects
- Missing specific projects that you know exist

**Possible Causes and Solutions:**

1. **Search Path Issues**
   - **Problem:** Server not looking in the right directories
   - **Solution:** Configure search paths in your `.env` file:
     ```
     KICAD_SEARCH_PATHS=~/pcb,~/Electronics,~/Projects/KiCad
     ```

2. **KiCad User Directory Override**
   - **Problem:** Custom KiCad user directory not being searched
   - **Solution:** Set `KICAD_USER_DIR` in `kicad-mcp-config.json` or `kicad_mcp/config.py` - it is **not** an environment variable

3. **File Extension Issues**
   - **Problem:** Projects not recognized due to file extensions
   - **Solution:** Ensure your KiCad projects have the `.kicad_pro` extension

## Debugging and Logging

### Checking Logs

To diagnose issues, check the server logs:

1. **Claude Desktop Logs (macOS)**
   - Server logs:
     ```bash
     tail -n 20 -F ~/Library/Logs/Claude/mcp-server-kicad.log
     ```
   - General MCP logs:
     ```bash
     tail -n 20 -F ~/Library/Logs/Claude/mcp.log
     ```

2. **Claude Desktop Logs (Windows)**
   - Check logs in:
     ```
     %APPDATA%\Claude\Logs\
     ```

## DRC and Export Feature Issues

### DRC Checks Failing

**Symptoms:**
- Error messages when running DRC checks
- Incomplete DRC results

**Possible Causes and Solutions:**

1. **KiCad CLI Tools Not Found**
   - **Problem:** Command-line tools not available
   - **Solution:** Ensure you have a complete KiCad installation with CLI tools. The server looks for `kicad-cli` in the installation set by `KICAD_APP_PATH` and only then on the system `PATH`

2. **PCB File Issues**
   - **Problem:** Invalid or corrupted PCB file
   - **Solution:** Verify the PCB file can be opened in KiCad

## SPICE Simulation Issues

See the [SPICE Simulation Guide](spice_guide.md) for how the simulation works. The messages below appear in the form's result or in Claude's answer.

1. **kicad-cli not found**
   - **Problem:** The KiCad installation in `KICAD_APP_PATH` does not exist (e.g. a different version is installed)
   - **Solution:** Set `_DEFAULT_APP_PATH` in `kicad_mcp/config.py` to your KiCad installation and restart the client. The simulation uses the ngspice of exactly this installation

2. **No simulation model: U1**
   - **Problem:** A seed component has no SPICE model
   - **Solution:** Assign one in KiCad (*Symbol Properties → Simulation Model*) or start from another component

3. **No DC path to ground: ...**
   - **Problem:** The listed nodes have no DC connection to node 0, e.g. an `output` port behind a capacitor
   - **Solution:** Set that port to `load` (e.g. `R 1G`), or grow the block with more seeds

4. **no ground net (node 0) on the block**
   - **Problem:** No ground net was found or chosen
   - **Solution:** Pick the reference net in the form, or add a ground symbol to the circuit's reference net in KiCad

5. **net ... has no known name in the SPICE export**
   - **Problem:** KiCad renames nets with special characters in the SPICE export, and no resistor, capacitor or inductor on the net shows the new name
   - **Solution:** Give the net a label without special characters in KiCad

6. **MIF-ERROR - unable to find definition of model ...**
   - **Problem:** ngspice's XSPICE code models are not loaded (needed for `POLY` sources in many vendor opamp models and for digital parts). A warning *"Code models not loaded"* names the files and the reason
   - **Solution:** Check that `lib/ngspice/*.cm` exists in the KiCad installation and that its path contains no apostrophe

7. **Warnings starting with "Not taken over"**
   - **Problem:** Part of the schematic that affects the block was not taken into the simulation (a coupling to an inductor outside the block, initial conditions for nodes outside, a component written as schematic text)
   - **Solution:** Take it into account when you read the result, or grow the block so it includes the missing parts

8. **unrecognized parameter (...) - ignored**
   - **Problem:** A vendor model uses parameters that only PSpice knows
   - **Solution:** None needed: ngspice skips them and the result is valid; the message is shown as a warning

9. **ngspice was reloaded after this error**
   - **Problem:** A deck error (e.g. a broken model line) left ngspice in a state it cannot recover from
   - **Solution:** Fix the cause named in the errors; the next simulation runs normally. If you instead get *"ngspice could not be reloaded ..."*, restart the MCP client

## Environment-Specific Issues

### macOS Issues

1. **Permissions**
   - **Problem:** Permission denied when accessing files
   - **Solution:** Ensure Terminal has full disk access in System Preferences > Security & Privacy

2. **Python Environment**
   - **Problem:** System Python vs. Homebrew Python confusion
   - **Solution:** Specify the full path to the Python interpreter in your client configuration

### Windows Issues

1. **Path Separator Issues**
   - **Problem:** Backslashes in Windows paths causing issues
   - **Solution:** Use forward slashes (/) in all paths, or double backslashes (\\\\)

2. **Command Execution**
   - **Problem:** Issues launching KiCad from the server
   - **Solution:** Ensure `KICAD_APP_PATH` (`_DEFAULT_APP_PATH` in `kicad_mcp/config.py`) points at your KiCad installation

### Linux Issues

1. **KiCad Installation Location**
   - **Problem:** KiCad installed in non-standard location
   - **Solution:** Set KICAD_APP_PATH to your KiCad installation location

2. **Permission Issues**
   - **Problem:** Unable to access certain files
   - **Solution:** Check file permissions with `ls -la` and adjust with `chmod` if needed

## Still Having Issues?

If you're still experiencing problems:

1. Use the MCP Inspector for direct server testing:
   ```bash
   npx @modelcontextprotocol/inspector uv --directory . run main.py
   ```
