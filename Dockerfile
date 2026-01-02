FROM nvidia/cuda:12.6.0-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    python3-venv \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY . /app/

# Make scripts executable
RUN chmod +x /app/setup.sh /app/install_nodes.sh

# Run setup script
RUN bash -c "source /app/setup.sh < /dev/null"

# Expose port
EXPOSE 5000

# Run the application in production mode
CMD ["/app/appenv/bin/python", "-m", "pynode", "--production", "--host", "0.0.0.0", "--port", "5000"]
