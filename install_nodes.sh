#!/bin/bash

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment not found. Please run setup.sh first."
    exit 1
fi

# Activate virtual environment if not already activated
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
else
    echo "Virtual environment already activated."
fi

# Iterate through node folders
echo "Installing node dependencies..."
NODE_COUNT=0
INSTALLED_COUNT=0

for node_dir in nodes/*/; do
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
