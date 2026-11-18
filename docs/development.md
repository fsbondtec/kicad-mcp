# Development Guide

This guide provides detailed information for developers who want to modify or extend the KiCad MCP Server.

## Development Environment Setup

1. **Set up your Python environment** (see [README](../README.md#build) for the full walkthrough):
   ```bash
   # uv
   uv sync

   # or conda
   conda env create -f environment.yml
   conda activate kicad-mcp
   pip install -e .
   ```

2. **Run the server**:
   ```bash
   python main.py
   ```

3. **Use the MCP Inspector** for debugging:
   ```bash
   npx @modelcontextprotocol/inspector uv --directory . run main.py
   ```

## Project Structure

The KiCad MCP Server follows a modular architecture:

```
kicad-mcp/
├── main.py                                             # Entry point
├── kicad_mcp/                                          # Main package
│   ├── __init__.py
│   ├── server.py                                       # Server creation and setup
│   ├── config.py                                       # Configuration settings
│   ├── context.py                                      # Lifespan context management
│   ├── resources/                                      # Resource handlers
│   │   ├── __init__.py
│   │   ├── projects.py                                 # Project listing resources
│   │   ├── files.py                                    # File content resources
│   │   ├── drc_resources.py                            # DRC report resources
│   │   └── svg_viewer_resources.py                     # SVG viewer app resource
│   ├── tools/                                          # Tool handlers
│   │   ├── __init__.py
│   │   ├── project_tools.py                            # Project management tools
│   │   ├── drc_tools.py                                # DRC check tools
│   │   ├── graph_tools.py                              # Analyse schematic/PCB in graph structure, path highlighting
│   │   ├── spice_tools.py                              # SPICE simulation UI and run_simulation
│   │   └── rag_tools.py                                # Datasheet search tools
│   └── utils/                                          # Utility functions
│       ├── __init__.py
│       ├── file_utils.py                               # File handling utilities
│       ├── cli_drc.py                                  # DRC check utils
│       ├── kicad_utils.py                              # KiCad-specific functions
│       ├── drc_history.py                              # DRC history tracking
│       ├── graph_analysis.py                           # Methods to create and search in Graphs
│       ├── wire_graph.py                               # Geometric wire/label graph for schematics
│       ├── net_parser.py                               # Parse Netlist
│       ├── schematic_cache.py                          # Cached kicad-cli exports per schematic (graph, SPICE netlist)
│       ├── spice/                                      # SPICE simulation of a block
│       │   ├── __init__.py
│       │   ├── block.py                                # Grow a simulatable block from seed components
│       │   ├── deck.py                                 # Seeds -> block -> isolated SPICE deck, deck validation
│       │   ├── fields.py                               # Simulation form fields -> SPICE text, field checks
│       │   ├── ui.py                                   # prefab_ui view of the simulation UI
│       │   └── runner.py                               # Run a deck through ngspice, format the result
│       ├── svg_utils.py                                # SVG plotting and path highlighting
│       ├── svg_file_server.py                          # Local HTTP server for SVG previews
│       ├── get_datasheets.py                           # Datasheet download pipeline
│       ├── chunking_utils.py                           # Markdown chunking for RAG
│       ├── search_rag.py                               # FAISS-backed datasheet search
│       └── env.py                                      # Environment variable handling
```

## Adding New Features

### Creating a New Resource

Resources provide read-only data to the LLM. To add a new resource:

1. Add your function to an existing resource file or create a new one in `kicad_mcp/resources/`:

```python
from mcp.server.fastmcp import FastMCP

def register_my_resources(mcp: FastMCP) -> None:
    """Register my custom resources with the MCP server."""
    
    @mcp.resource("kicad://my-resource/{parameter}")
    def my_custom_resource(parameter: str) -> str:
        """Description of what this resource provides.
        
        Args:
            parameter: Description of parameter
            
        Returns:
            Formatted data for the LLM
        """
        # Implementation goes here
        return f"Formatted data about {parameter}"
```

2. Register your resources in `kicad_mcp/server.py`:

```python
from kicad_mcp.resources.my_resources import register_my_resources

def create_server() -> FastMCP:
    # ...
    register_my_resources(mcp)
    # ...
```

### Creating a New Tool

Tools are functions that perform actions or computations. To add a new tool:

1. Add your function to an existing tool file or create a new one in `kicad_mcp/tools/`:

```python
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context

def register_my_tools(mcp: FastMCP) -> None:
    """Register my custom tools with the MCP server."""
    
    @mcp.tool()
    async def my_custom_tool(parameter: str) -> Dict[str, Any]:
        """Description of what this tool does.
        
        Args:
            parameter: Description of parameter
            
        Returns:
            Dictionary with tool results
        """
        
        # Implementation goes here
        
        # Complete progress
        
        return {
            "success": True,
            "message": "Operation completed successfully",
            "result": "Some result data"
        }
```

2. Register your tools in `kicad_mcp/server.py`:

```python
from kicad_mcp.tools.my_tools import register_my_tools

def create_server() -> FastMCP:
    # ...
    register_my_tools(mcp)
    # ...
```

### Creating a New Prompt

Prompts are reusable templates for common interactions. To add a new prompt:

1. Add your function to an existing prompt file or create a new one in `kicad_mcp/prompts/`:

```python
from mcp.server.fastmcp import FastMCP

def register_my_prompts(mcp: FastMCP) -> None:
    """Register my custom prompts with the MCP server."""
    
    @mcp.prompt()
    def my_custom_prompt() -> str:
        """Description of what this prompt is for."""
        prompt = """
        I need help with [specific task] in KiCad. Please assist me with:
        
        1. [First aspect]
        2. [Second aspect]
        3. [Third aspect]
        
        My KiCad project is located at:
        [Enter the full path to your .kicad_pro file here]
        
        [Additional contextual information or instructions]
        """
        
        return prompt
```

2. Register your prompts in `kicad_mcp/server.py`:

```python
from kicad_mcp.prompts.my_prompts import register_my_prompts

def create_server() -> FastMCP:
    # ...
    register_my_prompts(mcp)
    # ...
```

## Testing

Run the whole suite from the project folder:

```bash
pytest
```

Tests that need KiCad carry markers, so the suite also runs on a machine without KiCad:

| Marker | Meaning |
|--------|---------|
| `requires_kicad` | Needs `kicad-cli` and ngspice of the KiCad installation in `KICAD_APP_PATH`; skipped when `kicad-cli` is not found |
| `slow` | Takes more than a few seconds |

```bash
pytest -m "not requires_kicad"

# One file or class
pytest --no-cov tests/test_spice_runner.py::TestPassband

# Show every test name
pytest -v
```

The SPICE simulation is covered by:

| File | Covers |
|------|--------|
| `test_spice_deck.py` | Value conversion, parsing the SPICE export, building and checking the deck |
| `test_spice_fields.py` | Form fields: analysis line, sources, input checks |
| `test_spice_block.py` | Growing the block, ports, ground nets, port role suggestions |
| `test_spice_runner.py` | Result formatting and pass band; ngspice runs (`requires_kicad`) |
| `test_spice_pipeline.py` | Whole pipeline on copies of KiCad's simulation demos (`requires_kicad`, `slow`) |

When you fix a bug, add a test that fails without the fix.

## Debugging

For debugging, use:

1. The Python debugger (pdb)
2. Output to stderr - `print(..., file=sys.stderr)` or `logging` - which ends up in the Claude Desktop server log (`%APPDATA%\Claude\logs\mcp-server-kicad.log`).
3. The MCP Inspector tool

## Performance Considerations

1. Use caching for expensive operations
2. Report progress to the user for long-running operations
3. Include proper error handling and fallbacks
4. Use asyncio for concurrent operations

