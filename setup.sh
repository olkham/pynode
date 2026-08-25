#!/bin/bash

# Create the virtual environment, or reuse an existing one so this script can
# be re-run to pick up new hardware or dependencies. Recreating is not just
# redundant: 'venv' rewrites appenv/bin/python, which fails while a process is
# using it (a running PyNode server, an IDE language server, or this shell if
# the venv is already activated).
if [ -x "appenv/bin/python" ]; then
    echo "Found existing virtual environment: appenv"
    echo "Reusing it ($(appenv/bin/python --version 2>&1)). Delete the appenv folder first if you want a clean rebuild."
else
    echo "Creating virtual environment..."
    python3 -m venv appenv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source appenv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Detect CUDA version and pick the matching PyTorch wheel index
echo "Detecting CUDA version..."
TORCH_INDEX=""
# Check if CUDA_VERSION is set as environment variable (e.g., in Docker)
if [ -n "$CUDA_VERSION" ]; then
    echo "CUDA $CUDA_VERSION detected from environment"
elif command -v nvidia-smi &> /dev/null && NVIDIA_SMI_OUTPUT=$(nvidia-smi 2>/dev/null) && CUDA_VERSION=$(echo "$NVIDIA_SMI_OUTPUT" | sed -n 's/.*CUDA \(UMD \)\?Version: \([0-9]\+\.[0-9]\+\).*/\2/p' | head -n 1) && [ -n "$CUDA_VERSION" ]; then
    echo "CUDA $CUDA_VERSION detected from nvidia-smi"
fi

if [ -n "$CUDA_VERSION" ]; then
    CUDA_MAJOR=$(echo $CUDA_VERSION | cut -d. -f1)
    CUDA_MINOR=$(echo $CUDA_VERSION | cut -d. -f2)

    if [[ "$CUDA_MAJOR" -ge 13 ]]; then
        echo "Installing PyTorch with CUDA 13.0 support (highest available; forward-compatible with CUDA 13.x)..."
        TORCH_INDEX=https://download.pytorch.org/whl/cu130
    elif [[ "$CUDA_MAJOR" -eq 12 && "$CUDA_MINOR" -eq 8 ]]; then
        echo "Installing PyTorch with CUDA 12.8 support..."
        TORCH_INDEX=https://download.pytorch.org/whl/cu128
    elif [[ "$CUDA_MAJOR" -eq 12 && "$CUDA_MINOR" -eq 6 ]]; then
        echo "Installing PyTorch with CUDA 12.6 support..."
        TORCH_INDEX=https://download.pytorch.org/whl/cu126
    elif [[ "$CUDA_MAJOR" -eq 12 ]]; then
        echo "Installing PyTorch with CUDA 12.1 support..."
        TORCH_INDEX=https://download.pytorch.org/whl/cu121
    elif [[ "$CUDA_VERSION" == "11.8"* ]]; then
        echo "Installing PyTorch with CUDA 11.8 support..."
        TORCH_INDEX=https://download.pytorch.org/whl/cu118
    else
        echo "Installing PyTorch with CUDA 11.8 support (default)..."
        TORCH_INDEX=https://download.pytorch.org/whl/cu118
    fi
elif [ -d "/usr/local/cuda" ]; then
    echo "CUDA toolkit found but version could not be determined. Installing PyTorch with CUDA 12.1 support..."
    TORCH_INDEX=https://download.pytorch.org/whl/cu121
else
    echo "CUDA not detected. Installing CPU-only PyTorch..."
    TORCH_INDEX=https://download.pytorch.org/whl/cpu
fi

# pip will NOT swap an already-installed torch for a different build flavor
# (an installed 2.x+cpu still satisfies the requirement 'torch'), so when
# re-running setup after a GPU change compare the installed flavor with the
# target and uninstall first if they differ.
TARGET_TORCH_BUILD="${TORCH_INDEX##*/}"
INSTALLED_TORCH_BUILD=$(python -c "import importlib.util as u; m=u.find_spec('torch') and __import__('torch'); print('' if not m else (m.__version__.split('+',1)[1] if '+' in m.__version__ else ('cu'+m.version.cuda.replace('.','') if m.version.cuda else 'cpu')))" 2>/dev/null)
if [ -n "$INSTALLED_TORCH_BUILD" ] && [ "$INSTALLED_TORCH_BUILD" != "$TARGET_TORCH_BUILD" ]; then
    echo "Installed PyTorch build ($INSTALLED_TORCH_BUILD) does not match target ($TARGET_TORCH_BUILD) - replacing it..."
    pip uninstall -y torch torchvision
fi
pip install torch torchvision --index-url "$TORCH_INDEX"

# Install PyNode in editable mode with all extras (dependencies are declared
# in pyproject.toml; torch/torchvision installed above are reused as-is)
echo "Installing the application and its dependencies..."
pip install -e ".[vision,mqtt]"

echo ""
echo "Setup complete! Virtual environment is activated."
echo ""

# Check if running in non-interactive mode (e.g., Docker build)
if [ -t 0 ]; then
    # Interactive mode - ask user
    read -p "Would you like to install node dependencies? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Installing node dependencies..."
        ./install_nodes.sh
    else
        echo "Skipping node dependencies installation."
        echo "You can install them later by running: ./install_nodes.sh"
    fi
else
    # Non-interactive mode - auto-install
    echo "Non-interactive mode detected. Installing node dependencies..."
    ./install_nodes.sh
fi

echo ""
echo "To activate the environment in the future, run: source appenv/bin/activate"
