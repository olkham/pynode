# Installation Guide

## Development Installation

Install PyNode in development mode (recommended for development):

```bash
# Clone or navigate to the project directory
cd pynode

# Install in editable mode (core dependencies only)
pip install -e .

# Optional extras (declared in pyproject.toml):
pip install -e .[vision]      # ML vision nodes (torch, ultralytics, supervision)
pip install -e .[mqtt]        # MQTT nodes (paho-mqtt)
pip install -e .[dev]         # Development tools (pytest, type stubs)
pip install -e .[vision,mqtt] # Everything
```

This installs PyNode as a package while keeping your source files editable.
Nodes whose optional dependencies are missing are simply skipped at startup,
so a core-only install still runs fine.

## Running PyNode

After installation, you can run PyNode in multiple ways:

### Option 1: Using the `pynode` command
```bash
pynode
```

### Option 2: Using Python module syntax
```bash
python -m pynode
```

### Option 3: With custom options
```bash
pynode --host 0.0.0.0 --port 5000 --production
```

## Command Line Options

- `--host`: Host address to bind to (default: 0.0.0.0)
- `--port`: Port to bind to (default: 5000)
- `--production`: Run in production mode using Waitress server

## Installing Node Dependencies

Some custom nodes have additional dependencies. To install them:

```bash
# Windows
install_nodes.bat

# Linux/Mac
./install_nodes.sh
```

## Uninstalling

```bash
pip uninstall pynode
```
