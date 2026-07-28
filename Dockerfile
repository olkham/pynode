FROM docker.io/nvidia/cuda:12.6.0-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_VERSION=12.6

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    python3-venv \
    git \
    wget \
    gosu \
    gfortran \
    libgl1-mesa-glx \
    libgtk-3-0 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev \
    libxvidcore-dev \
    libx264-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libopenblas-dev \
    liblapack-dev \
    portaudio19-dev \
    libasound2-dev \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    libudev-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY . /app/

# Derive the display version from git history, then remove .git to save
# space.  SETUPTOOLS_SCM_PRETEND_VERSION keeps pip install happy (PEP 440);
# the real version string is written to _version.py afterwards.
RUN chmod +x /app/setup.sh /app/install_nodes.sh && \
    RAW=$(git -C /app describe --tags --always 2>/dev/null || true) && \
    if echo "$RAW" | grep -qE '^v?[0-9]+\.[0-9]+'; then \
        VERSION=$(echo "$RAW" | sed 's/^v//'); \
    elif [ -n "$RAW" ]; then \
        VERSION="0.0.0+g${RAW}"; \
    else \
        VERSION="0.0.0"; \
    fi && \
    rm -rf /app/.git && \
    SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 bash -c "source /app/setup.sh < /dev/null" && \
    printf '__version__ = "%s"\n' "$VERSION" > /app/pynode/_version.py

# Create a non-root user and give it ownership of the app directory
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app

# Entrypoint ensures bind-mounted directories are writable by appuser
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Expose port
EXPOSE 5000

# Health check (uses the bundled Python interpreter; no extra tools required)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["/app/appenv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/')"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["/app/appenv/bin/python", "-m", "pynode", "--production", "--host", "0.0.0.0", "--port", "5000"]
