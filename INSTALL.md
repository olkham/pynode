# Installation Guide

PyNode is published on PyPI as **`pynode-flow`** (the import package is still
`pynode`).

## Install from PyPI

```bash
# Core install (Flask API + built-in nodes that need no extra packages)
pip install pynode-flow

# Everything PyPI-installable (all optional nodes)
pip install "pynode-flow[full]"
```

Nodes whose optional dependencies are missing are simply skipped at startup, so
a core-only install still runs fine.

> **Warning — conflicting `pynode` package:** an unrelated project on PyPI is
> named `pynode`, and it also installs a top-level `pynode` package. If it is
> present in the same environment the two clobber each other (symptoms include
> `ImportError: cannot import name '__version__' from 'pynode' (unknown
> location)`). Remove it before or after installing:
>
> ```bash
> pip uninstall pynode
> ```

### Optional extras

Install only the node groups you need:

| Extra | Installs | Nodes it enables |
|-------|----------|------------------|
| `vision` | ultralytics, torch, torchvision, supervision | UltralyticsNode, TrackerNode, DrawPredictionsNode, … |
| `mqtt` | paho-mqtt | MQTTNode |
| `camera` | framesource[full] | FrameSourceNode |
| `inference` | onnxruntime (+ `vision`) | InferenceNode |
| `vlm` | transformers, qwen-vl-utils, Pillow (+ `vision`) | Qwen3VLMNode |
| `upload` | roboflow | RoboflowUploadNode |
| `discovery` | zeroconf | mDNSNode |
| `full` | all of the above | every PyPI-installable node |
| `dev` | pytest, type stubs | (development only) |

```bash
pip install "pynode-flow[vision,mqtt]"   # pick specific groups
pip install "pynode-flow[full]"          # or grab everything
```

> **Note:** `pip install pynode-flow` (or any extra) installs **only** what is
> declared in `pyproject.toml`. It does **not** run the per-node
> `requirements.txt` files — those are covered by the extras above, or by the
> `pynode-install-nodes` command below.

## Development Installation

Install PyNode from a source checkout in editable mode (recommended for
development):

```bash
# Clone or navigate to the project directory
cd pynode

# Install in editable mode (core dependencies only)
pip install -e .

# Optional extras (same names as above):
pip install -e ".[vision]"      # ML vision nodes
pip install -e ".[mqtt]"        # MQTT node
pip install -e ".[full]"        # everything PyPI-installable
pip install -e ".[dev]"         # development tools (pytest, type stubs)
```

This installs PyNode as a package while keeping your source files editable.

> **Versioning:** the package version is derived from git tags by
> `setuptools_scm`. A clean checkout at tag `v0.2.0` builds as `0.2.0`; commits
> after a tag build as a dev version. To cut a release, tag the commit
> (`git tag v0.2.0 && git push --tags`) — see [Publishing](#publishing-to-pypi).

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

A few nodes rely on packages that cannot live in `pyproject.toml` — for example
the Omron/Sentech `stapipy` SDK (OmronCameraNode), which is a vendor download
rather than a PyPI package. Each such node ships its own `requirements.txt`.

**If you installed from PyPI**, use the bundled command to walk the installed
node folders and install their requirements:

```bash
pynode-install-nodes            # install every node's requirements.txt
pynode-install-nodes --list     # list nodes that have a requirements.txt
pynode-install-nodes --node MQTTNode --node mDNSNode  # only specific nodes
pynode-install-nodes --dry-run  # preview without installing
```

**If you're working from a source checkout**, you can instead run the helper
scripts, which iterate the node folders in the repo:

```bash
# Windows
install_nodes.bat

# Linux/Mac
./install_nodes.sh
```

## Publishing to PyPI

Releases are published by `.github/workflows/publish.yaml` via PyPI
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC — no API
token is stored in the repo). To release:

1. Configure a trusted publisher for the `pynode-flow` project on PyPI, pointing
   at this repository / `publish.yaml`, and create a GitHub environment named
   `pypi` (one-time setup).
2. Tag the release commit and push the tag:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
   The tag drives the version via `setuptools_scm`. (A manual
   `workflow_dispatch` run must also be dispatched from a tag ref, otherwise the
   build produces a dev version that PyPI rejects.)

## Uninstalling

```bash
pip uninstall pynode-flow
```
