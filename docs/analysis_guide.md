# KiCad Schematic Analysis Guide

This guide explains how to use the Schematic design analysis features in the KiCad MCP Server.

## Overview

The Schematic design analysis functionality allows you to:

1. Extract and analyze information from schematics
2. Validate projects for completeness and correctness
3. Get insights about components and connections
4. Find neighbors to a chosen Radius of components
5. Find Paths between Components including Power Paths or excludin Power Paths

- the first time the graph is built and information is read it can take a while after that Graph Information is cached and requests are faster

## Quick Reference

| Task | Example Prompt |
|------|---------------|
| Get schematic info | `What components are in my schematic at /path/to/project.kicad_sch?` |
| Analyze PCB | `Analyze the Schematic layout at /path/to/project.kicad_pcb` |

## Using Schematic Analysis Features

### Schematic Information

To extract information from a schematic:

```
What components are in my schematic at /path/to/project.kicad_sch?
```

This will provide:
- A list of all components in the schematic
- Component values and footprints
- Connection information
- Basic schematic structure

```
Analyze the main component in more detail.
```

This will provide:
- A list of all neighbors of the component to a certain depth 
- component values and references
- Connection information


## Available Resources

The server provides several resources for accessing design information:

- `kicad://schematic/{schematic_path}` - Information from a schematic file
- `kicad://pcb/{pcb_path}` - Information from a PCB file

These resources can be accessed programmatically by other MCP clients or directly referenced in conversations.

## Tips for Better Analysis

### Focus on Specific Elements

You can ask for analysis of specific aspects of your design:

```
What are all the resistor values in my schematic at /path/to/project.kicad_sch?
```

```
Show me all the power connections in my schematic at /path/to/project.kicad_sch
```

- sometimes if very general questions are asked Claude uses DRC and to analyse the circuit if that is the case just deactivate DRC Tool

## Common Analysis Tasks

### Finding Specific Components

To locate components in your schematic:

```
Find all decoupling capacitors in my schematic at /path/to/project.kicad_sch
```

This helps with understanding component usage and ensuring proper design practices.

### Identifying Signal Paths

To trace signals through your design:

```
Trace the clock signal path in my schematic at /path/to/project.kicad_sch
```

This helps with understanding signal flow and potential issues.


## Troubleshooting

### Schematic Reading Errors

If the server can't read your schematic:

1. Verify the file exists and has the correct extension (.kicad_sch)
2. Check if the file is a valid KiCad schematic
3. Ensure you have read permissions for the file
4. Try the analysis on a simpler schematic to isolate the issue


## Advanced Usage

### Design Reviews

Use the analysis features for comprehensive design reviews:

```
Review the power distribution network in my schematic at /path/to/project.kicad_sch
```