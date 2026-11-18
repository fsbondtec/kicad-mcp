# SPICE Simulation Guide

This guide explains how to simulate a part of your schematic with ngspice: you pick one or more seed components, the server cuts the surrounding block out of the schematic, and an interactive form lets you decide what drives the block and what to measure.

## Overview

The SPICE simulation:
1. Exports the schematic's SPICE netlist with `kicad-cli` (cached per schematic, exported again only after a change)
2. Grows a **block** from the seed components over the parts that have a SPICE value or simulation model
3. Finds the block's **ports** (nets that leave the block) and the **supply rails** it touches
4. Shows a form in the MCP client: role and value per port, source per rail, reference net, analysis
5. Builds an isolated SPICE deck from the block and your entries, checks it and runs it through **KiCad's own ngspice**
6. Shows node voltages, currents, a diagram and the deck itself

You do not need to draw a test bench in KiCad: the form replaces the rest of the circuit with sources and loads.

## Requirements

- **Windows** with KiCad 9.0 or newer. The server uses `kicad-cli` and the ngspice library (`ngspice.dll`) from the KiCad installation set by `KICAD_APP_PATH`, plus KiCad's XSPICE code models under `lib/ngspice`. On Linux and macOS the simulation is currently not supported.
- An MCP client that can display MCP apps (e.g. Claude Desktop), because the simulation is set up in an interactive form.
- Components in the block need a SPICE value (R, C, L, sources) or a simulation model (KiCad's built-in models, or a model file via *Symbol Properties → Simulation Model*).

## MCP Tools

| Tool | Description |
|------|-------------|
| `open_spice_simulation(project_path, schematic_path, seed_components)` | Grows the block from the seeds (comma-separated references, e.g. `"R1"` or `"R1,C3"`) and opens the simulation form. |
| `run_simulation(...)` | Called by the form's **Simulate** button: assembles, checks and runs the deck. |

### Example prompts

```
Simulate the RC filter around R1 in my Tiefpass project.
Open the SPICE simulation for C34 in my flameoff schematic.
What is the cut-off frequency of the filter at U3's input? Simulate it.
```

Claude finds the project and schematic paths, calls `open_spice_simulation`, and you complete the form.

## How the Block Is Grown

Starting from the seeds, the block grows component by component over the nets between them and stops at:

- **global nets** (power and ground symbols such as `GND`, `+5V`): they become supply rails, not ports,
- **components without a simulation model** (e.g. an MCU): the net to them becomes a port,
- **nets with more than 10 connections** (likely a bus): reported in the hints,
- the limits of **6 steps** from a seed or **60 components**: reported as "Block was truncated".

Test points and mounting holes are passed through. A seed without a model is rejected with *"No simulation model"*.

## The Simulation Form

### Ports

Every net that leaves the block is a port. Pick a role for each:

| Role | Meaning | Value |
|------|---------|-------|
| `input` | An ideal voltage source to ground drives the net | DC, PULSE or SIN, plus an AC amplitude for `.ac` |
| `output` | The block drives the net, the rest of the circuit only listens: left open and measured | – |
| `load` | The rest of the circuit is an impedance to ground | R, C or L with value |

A role is pre-selected from the pin types outside the block: a driving pin (`output`, `power_out`) outside suggests `input`, only receiving pins suggest `output`. Ports with passive or unclear pins outside are marked *"Role unclear"* - check them.

### Supplies and reference net

Each supply rail the block touches gets its own source. The voltage is guessed from the net name (`+5V`, `+3V3`, `-12V`); leave it empty and the rail gets no source (you get a warning). The reference net becomes SPICE node 0: `GND` or `0` is chosen automatically, otherwise pick it in the form.

### Analyses

| Analysis | Fields | Result |
|----------|--------|--------|
| Operating point (`.op`) | – | DC voltage of every node, current of every part |
| Frequency response (`.ac`) | sweep `dec`/`oct`/`lin`, points, start and stop frequency | pass band (−3 dB relative to the maximum), gain and phase at the stop frequency, diagram in dB |
| Transient (`.tran`) | step, end time, optional start time and max. step, UIC | min/max/end voltage per node, peak and RMS current, diagram |

`.ac` needs an AC amplitude at one input port or supply. `.tran` with only DC sources gives a constant curve, unless UIC (start all capacitors and inductors at 0) is set.

### Units

SPICE prefixes are case-insensitive: `k`, `Meg`, `m` (milli), `u`, `n`, `p`, `f` (femto).

- **`M` is milli in SPICE.** The form rejects `1M`; write `1Meg`. Values in the schematic (`1M`, `4k7`, `2200uF;63V`, `10k/1%`) are converted automatically.
- **`F` is femto.** A capacitor value `1F` is 1 femtofarad, in KiCad's simulator as well; for 1 farad write `1`. The check warns about such values.
- Use a point, not a comma, as decimal separator.

## What Is Taken from the Schematic

Besides the components of the block, the deck contains:

| From the schematic | In the block deck |
|--------------------|-------------------|
| `.include` / model cards used by the block | taken over |
| SPICE directives in schematic text (`.options`, `.param`, `.func`, `.temp`, `.lib`, ...) | taken over |
| `.ic` / `.nodeset` | only the values for nodes of the block |
| Coupled inductors (`K1 L1 L2 0.98`) | taken over if both inductors are in the block |
| Analyses and output commands (`.tran`, `.ac`, `.probe`, `.meas`, `.control` blocks) | dropped - the form sets the analysis |

Anything that would change the block's result but is **not** taken over is listed as a warning starting with *"Not taken over"* (a coupling to an inductor outside the block, `.ic` values for nodes outside, a component written as schematic text). Take these warnings into account when you read a successful result.

KiCad itself only exports a schematic text if it starts with a SPICE directive (`.`) or a coupling statement; any other text is ignored.

## Checks Before and After the Run

Before ngspice starts, the deck is checked. Typical messages:

| Message | Meaning |
|---------|---------|
| *No source in the deck* | no input port and no supply source - set at least one port to `input` |
| *No DC path to ground: ...* | these nodes float (e.g. only capacitors to ground) - add a `load` such as `R 1G` or grow the block |
| *no ground net (node 0) on the block* | choose a reference net, or add a ground symbol in KiCad |
| *value '...' is not a SPICE number* | a component value cannot be read (e.g. a part number in the Value field) |
| *... are in parallel* | two voltage sources on the same nets |

ngspice messages that only say a model parameter was ignored (common with PSpice vendor models) are shown as warnings; the result is valid. If ngspice ends up in a state it cannot recover from, it is reloaded automatically and the next simulation runs normally.

## Limitations

- Input ports are **ideal** voltage sources; a source impedance is not modelled.
- Nets with special characters in their name are renamed by KiCad in the SPICE export; the new name is only known through a resistor, capacitor or inductor on the net. Otherwise you get an error - give the net a plain label in KiCad.
- Resistors with a formula value (`R='time > 1m ? 10 : 20'`) are rejected.
- Parameters you enter for a **built-in** model in KiCad (e.g. `bf=200` for an NPN) are written by KiCad on continuation lines and are currently not taken over; the part is simulated with ngspice's default parameters. Models from a model file are not affected.
- A `.subckt` definition written as schematic text is not supported.
- Current-controlled switches are exported incorrectly by KiCad (missing sense source).
- There is no time limit for ngspice; a very long `.tran` blocks further simulations until it ends.
