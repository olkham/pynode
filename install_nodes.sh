#!/bin/bash

# Activate virtual environment if not already activated
if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "Virtual environment already activated."
elif [ -d "appenv" ]; then
    echo "Activating virtual environment (appenv)..."
    source appenv/bin/activate
elif [ -d ".venv" ]; then
    echo "Activating virtual environment (.venv)..."
    source .venv/bin/activate
else
    echo "Warning: No virtual environment found (checked appenv and .venv)."
    read -p "Would you like to install into the current environment? (y/n): " USE_CURRENT
    if [[ "$USE_CURRENT" != "y" && "$USE_CURRENT" != "Y" ]]; then
        echo "Aborted. Please run setup.sh first or create a virtual environment."
        exit 1
    fi
    echo "Proceeding with the current environment..."
fi

# Iterate through node folders
echo "Installing node dependencies..."
NODE_COUNT=0
INSTALLED_COUNT=0

for node_dir in pynode/nodes/*/; do
    if [ -d "$node_dir" ]; then
        node_name=$(basename "$node_dir")
        requirements_file="${node_dir}requirements.txt"
        
        if [ -f "$requirements_file" ]; then
            echo "Installing requirements for $node_name..."
            pip install -r "$requirements_file"
            
            if [ $? -eq 0 ]; then
                ((INSTALLED_COUNT++))
                echo "✓ $node_name dependencies installed successfully"
            else
                echo "✗ Failed to install dependencies for $node_name"
            fi
            ((NODE_COUNT++))
        fi
    fi
done

echo ""
echo "Installation complete!"
echo "Processed $NODE_COUNT nodes with requirements.txt files"
echo "Successfully installed dependencies for $INSTALLED_COUNT nodes"
