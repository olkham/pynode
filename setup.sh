#!/bin/bash

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv appenv

# Activate virtual environment
echo "Activating virtual environment..."
source appenv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Detect CUDA version and install appropriate PyTorch
echo "Detecting CUDA version..."
# Check if CUDA_VERSION is set as environment variable (e.g., in Docker)
if [ -n "$CUDA_VERSION" ]; then
    echo "CUDA $CUDA_VERSION detected from environment"
elif command -v nvidia-smi &> /dev/null; then
    CUDA_VERSION=$(nvidia-smi | grep "CUDA Version" | sed -n 's/.*CUDA Version: \([0-9]\+\.[0-9]\+\).*/\1/p')
    echo "CUDA $CUDA_VERSION detected from nvidia-smi"
    
    # Determine PyTorch installation command based on CUDA version
    CUDA_MAJOR=$(echo $CUDA_VERSION | cut -d. -f1)
    CUDA_MINOR=$(echo $CUDA_VERSION | cut -d. -f2)
    
    if [[ "$CUDA_MAJOR" -eq 13 && "$CUDA_MINOR" -eq 0 ]]; then
        echo "Installing PyTorch with CUDA 13.0 support (highest available for CUDA 13.0)..."
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
    elif [[ "$CUDA_MAJOR" -eq 12 && "$CUDA_MINOR" -eq 8 ]]; then
        echo "Installing PyTorch with CUDA 12.8 support..."
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
    elif [[ "$CUDA_MAJOR" -eq 12 && "$CUDA_MINOR" -eq 6 ]]; then
        echo "Installing PyTorch with CUDA 12.6 support..."
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
    elif [[ "$CUDA_MAJOR" -eq 12 ]]; then
        echo "Installing PyTorch with CUDA 12.1 support..."
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
    elif [[ "$CUDA_VERSION" == "11.8"* ]]; then
        echo "Installing PyTorch with CUDA 11.8 support..."
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
    else
        echo "Installing PyTorch with CUDA 11.8 support (default)..."
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
    fi
elif [ -d "/usr/local/cuda" ]; then
    echo "CUDA toolkit found but version could not be determined. Installing PyTorch with CUDA 12.1 support..."
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
else
    echo "CUDA not detected. Installing CPU-only PyTorch..."
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
fi

# Install remaining requirements (excluding torch/torchvision as they're already installed)
echo "Installing remaining requirements..."
pip install -r requirements.txt

echo "Installing the application in editable mode..."
pip install -e .

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
