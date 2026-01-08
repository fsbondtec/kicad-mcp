# KiCad Design Rule Check (DRC) Guide

This guide explains how to use the Design Rule Check (DRC) features in the KiCad MCP Server.

## Overview

The Design Rule Check (DRC) functionality allows you to:

1. Run DRC checks on your KiCad PCB designs
2. Get detailed reports of violations
3. Track your progress over time as you fix issues
4. Compare current results with previous checks

It does this all by using the `kicad-cli` command-line tool to run DRC checks without requiring a running instance of KiCad.

## Prerequisites

For optimal DRC functionality with KiCad 9.0+, you should have:

- KiCad 9.0 or newer installed
- `kicad-cli` available in your system PATH (included with KiCad 9.0+)

## Using DRC Features

### Running a DRC Check

To run a DRC check on your KiCad project:

1. In Claude Desktop, select the KiCad MCP server from the tools dropdown
2. Use the `run_drc_check` tool with your project path:

```
Please run a DRC check on my project at /Users/username/Documents/KiCad/my_project/my_project.kicad_pro
```

The tool will:
- Use the kicad CLI to run the DRC check
- Analyze your PCB design for rule violations
- Generate a comprehensive report
- Save the results to your DRC history
- Compare with previous runs (if available)

### Viewing DRC Reports

There are two ways to view DRC information:

#### Current DRC Report

To view the current DRC status of your project:

```
Show me the DRC report for /Users/username/Documents/KiCad/my_project/my_project.kicad_pro
```

This will load the `kicad://drc/project_path` resource, showing:
- Total number of violations
- Categorized list of issues
- Violation details with locations
- Recommendations for fixing common issues

#### DRC History

To see how your project's DRC status has changed over time:

```
Show me the DRC history for /Users/username/Documents/KiCad/my_project/my_project.kicad_pro
```

This will load the `kicad://drc/history/project_path` resource, showing:
- A visual trend of violations over time
- Table of all DRC check runs
- Comparison between first and most recent checks
- Progress indicators

## Understanding DRC Results

### Violation Categories

Common DRC violation categories include:

| Category | Description | Common Fixes |
|----------|-------------|--------------|
| Clearance | Items are too close together | Increase spacing, reroute traces |
| Track Width | Traces are too narrow | Increase trace width, reconsider current requirements |
| Annular Ring | Via rings are too small | Increase via size, adjust PCB manufacturing settings |
| Drill Size | Holes are too small | Increase drill diameter, check manufacturing capabilities |
| Silkscreen | Silkscreen conflicts with pads | Adjust silkscreen position, resize text |
| Courtyard | Component courtyards overlap | Adjust component placement, reduce footprint sizes |

### Integrating with KiCad

The DRC checks are designed to work alongside KiCad's built-in DRC tool:

1. Run the MCP server's DRC check to get an overview and track progress
2. Use KiCad's built-in DRC for interactive fixes (which highlight the exact location in the editor)
3. Re-run the MCP server's DRC to verify your fixes and update the history

## Troubleshooting

### DRC Check Fails

If the DRC check fails to run:

1. Ensure your KiCad project exists at the specified path
2. Verify that the project contains a PCB file (.kicad_pcb)
3. Check your KiCad installation: Verify `kicad-cli` is in your PATH or in a standard installation location
4. Try using the full absolute path to your project file

If you continue to experience issues, check the server logs for more detailed error information.
