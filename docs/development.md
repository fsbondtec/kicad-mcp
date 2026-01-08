# Development Guide

This guide provides detailed information for developers who want to modify or extend the KiCad MCP Server.

## Development Environment Setup

1. **Set up your Python environment**:
   ```bash
   # Create and activate a virtual environment
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   
   # Install development dependencies
   pip install -r requirements.txt
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
│   ├── tools/                                          # Tool handlers
│   │   ├── __init__.py
│   │   ├── project_tools.py                            # Project management tools
│   │   ├── drc_tools.py                                # DRC check tools
|   |   |-- graph_tools.py                              #analyse schematic in graph structure

│   └── utils/                                          # Utility functions
│       ├── __init__.py
│       ├── file_utils.py                               # File handling utilities
│       ├── cli_drc.py                                  # DRC check utils
│       ├── kicad_utils.py                              # KiCad-specific functions
│       ├── drc_history.py                              # DRC history tracking
│       ├── graph_analysis.py                           # Methods to create and search in Graphs
│       ├── kicad_cli.py                                # find Kicad CLI
│       ├── net_parser.py                               # Parse Netlist
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
    async def my_custom_tool(parameter: str, ctx: Context) -> Dict[str, Any]:
        """Description of what this tool does.
        
        Args:
            parameter: Description of parameter
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with tool results
        """
        # Report progress to the user
        await ctx.report_progress(10, 100)
        ctx.info(f"Starting operation on {parameter}")
        
        # Implementation goes here
        
        # Complete progress
        await ctx.report_progress(100, 100)
        ctx.info("Operation complete")
        
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

## Using the Lifespan Context

The KiCad MCP Server uses a typed lifespan context to share data across requests:

```python
from kicad_mcp.context import KiCadAppContext

@mcp.tool()
def my_tool(parameter: str, ctx: Context) -> Dict[str, Any]:
    """Example tool using lifespan context."""
    # Access the typed context
    app_context: KiCadAppContext = ctx.request_context.lifespan_context
    
    # Check if KiCad modules are available
    if app_context.kicad_modules_available:
        # Use KiCad Python modules
        pass
    else:
        # Fall back to alternative method
        pass
    
    # Use the cache to store expensive results
    cache_key = f"my_operation_{parameter}"
    if cache_key in app_context.cache:
        return app_context.cache[cache_key]
    
    # Perform operation
    result = {}
    
    # Cache the result
    app_context.cache[cache_key] = result
    
    return result
```

## Testing

To run tests:

```bash
# Run all tests
pytest

# Run specific tests:
pytest tests/test_tools.py::test_run_drc_check
```

## Debugging

For debugging, use:

1. The Python debugger (pdb)
2. Print statements to the console (captured in Claude Desktop logs)
3. The MCP Inspector tool

## Performance Considerations

1. Use caching for expensive operations
2. Report progress to the user for long-running operations
3. Include proper error handling and fallbacks
4. Use asyncio for concurrent operations

