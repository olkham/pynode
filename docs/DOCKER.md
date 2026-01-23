# Docker Setup Guide

This guide covers running PyNode in Docker containers with GPU acceleration and network service discovery support.

## Prerequisites

### Required
- Docker Engine 20.10+ or Docker Desktop
- Docker Compose v2.0+

### Optional (for GPU support)
- NVIDIA GPU with compatible drivers
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## Quick Start

### 1. Set Host IP for mDNS Discovery

For mDNS service discovery to work correctly, set the `HOST_IP` environment variable to your host machine's IP address:

```bash
export HOST_IP=$(hostname -I | awk '{print $1}')
```

**Why is this needed?**

When PyNode runs inside Docker, it uses a container-internal IP address (e.g., 172.x.x.x). The mDNS Broadcast Node needs to advertise your host machine's actual IP address so other devices on your local network can discover and connect to the service.

### 2. Start the Container

```bash
docker compose up -d
```

This will:
- Build the Docker image with CUDA 12.6 support
- Install PyTorch with CUDA 12.6
- Install all Python dependencies
- Install node-specific requirements
- Start the PyNode server on port 5000

### 3. Access PyNode

- **From the host machine**: http://localhost:5000
- **From other devices on your network**: http://YOUR_HOST_IP:5000

## Configuration

### Docker Compose

The `docker-compose.yml` file includes:

```yaml
services:
  pynode:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "5000:5000"
    environment:
      - HOST_IP=${HOST_IP}
    volumes:
      - ./workflows:/app/workflows
      - ./logs:/app/logs
    runtime: nvidia
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

### Environment Variables

- `HOST_IP`: Your host machine's IP address (required for mDNS)
- `CUDA_VERSION`: CUDA version (set to 12.6 in Dockerfile)
- `PYTHONUNBUFFERED`: Enables real-time log output

### Persistent Data

The following directories are mounted as volumes:
- `./workflows` - Workflow JSON files
- `./logs` - Application logs

## Docker Images

### GPU-Enabled (Default)

Uses `Dockerfile` with NVIDIA CUDA 12.6:
- Base image: `nvidia/cuda:12.6.0-devel-ubuntu22.04`
- Includes CUDA runtime and development libraries
- Automatically detects and uses GPU for inference

### CPU-Only

Uses `Dockerfile.cpu` for systems without NVIDIA GPUs:

```bash
docker compose -f docker-compose.cpu.yml up -d
```

## Building the Image

### Build with Docker Compose

```bash
docker compose build
```

### Build manually

```bash
# GPU version
docker build -t pynode:latest .

# CPU version
docker build -f Dockerfile.cpu -t pynode:cpu .
```

### Build with custom CUDA version

Edit the `Dockerfile` and change the base image:

```dockerfile
FROM nvidia/cuda:YOUR_CUDA_VERSION-devel-ubuntu22.04
```

Update the `CUDA_VERSION` environment variable to match:

```dockerfile
ENV CUDA_VERSION=YOUR_VERSION
```

## Running the Container

### With Docker Compose (Recommended)

```bash
# Set host IP
export HOST_IP=$(hostname -I | awk '{print $1}')

# Start in detached mode
docker compose up -d

# View logs
docker compose logs -f

# Stop container
docker compose down
```

### With Docker Run

```bash
docker run -d \
  --name pynode \
  --runtime=nvidia \
  --gpus all \
  -p 5000:5000 \
  -e HOST_IP=$(hostname -I | awk '{print $1}') \
  -v $(pwd)/workflows:/app/workflows \
  -v $(pwd)/logs:/app/logs \
  pynode:latest
```

## GPU Access

### Verify GPU Access

Check if the container can access your GPU:

```bash
docker exec -it pynode nvidia-smi
```

You should see output showing your GPU(s) and CUDA version.

### Check PyTorch CUDA Support

```bash
docker exec -it pynode /app/appenv/bin/python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}'); print(f'Device count: {torch.cuda.device_count()}')"
```

Expected output:
```
CUDA available: True
CUDA version: 12.6
Device count: 1
```

## Installed Dependencies

The Docker image includes:

### System Packages
- Python 3.10
- Git, wget, gfortran
- OpenCV dependencies (libgl1-mesa-glx, libgtk-3-0, etc.)
- Video codec libraries (libavcodec, libavformat, etc.)
- Audio libraries (portaudio19-dev, libasound2-dev)
- USB device support (libusb-1.0-0)
- Image format libraries (libjpeg, libpng, libtiff)
- Math libraries (libopenblas, liblapack)

### Python Packages
- PyTorch with CUDA 12.6 support
- Flask web framework
- OpenCV for image processing
- Ultralytics YOLO
- Geti SDK
- ONNX Runtime
- And all node-specific requirements

## Troubleshooting

### GPU Not Detected

**Problem**: Container can't access GPU or PyTorch reports CUDA unavailable.

**Solution**:
1. Verify NVIDIA drivers are installed on host:
   ```bash
   nvidia-smi
   ```

2. Install NVIDIA Container Toolkit:
   ```bash
   # Ubuntu/Debian
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
   sudo systemctl restart docker
   ```

3. Verify Docker can see GPU:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
   ```

### mDNS Not Working

**Problem**: Other devices can't discover the service via mDNS.

**Solution**:
1. Ensure `HOST_IP` is set before starting:
   ```bash
   export HOST_IP=$(hostname -I | awk '{print $1}')
   echo $HOST_IP  # Verify it shows your actual IP
   docker compose up -d
   ```

2. Check mDNS is broadcasting with correct IP:
   ```bash
   docker exec -it pynode /app/appenv/bin/python -c "import os; print(f'HOST_IP: {os.environ.get(\"HOST_IP\", \"NOT SET\")}')"
   ```

3. Verify network mode allows mDNS:
   - Docker Compose should use `network_mode: bridge` or default
   - Don't use `host` network mode on Linux as it may cause port conflicts

### Build Failures

**Problem**: Docker build fails during dependency installation.

**Solution**:
1. Check available disk space:
   ```bash
   df -h
   ```

2. Clear Docker build cache:
   ```bash
   docker builder prune -a
   ```

3. Build with verbose output:
   ```bash
   BUILDKIT_PROGRESS=plain docker compose build
   ```

### Permission Issues

**Problem**: Container can't write to mounted volumes.

**Solution**:
1. Create directories with proper permissions:
   ```bash
   mkdir -p workflows logs
   chmod 777 workflows logs
   ```

2. Or run container with specific user:
   ```yaml
   # In docker-compose.yml
   user: "${UID}:${GID}"
   ```

### Port Already in Use

**Problem**: Port 5000 is already bound by another service.

**Solution**:
1. Use a different port:
   ```yaml
   # In docker-compose.yml
   ports:
     - "8080:5000"  # Map to port 8080 instead
   ```

2. Or stop the conflicting service:
   ```bash
   sudo lsof -i :5000
   sudo kill <PID>
   ```

## Advanced Configuration

### Custom Node Installation

To add custom nodes, mount your nodes directory:

```yaml
volumes:
  - ./my-custom-nodes:/app/pynode/nodes/CustomNodes
```

### Development Mode

Mount the entire source for live code updates:

```yaml
volumes:
  - .:/app
command: /app/appenv/bin/python -m pynode --debug --host 0.0.0.0 --port 5000
```

### Multiple Instances

Run multiple PyNode instances with different ports:

```bash
# Instance 1
export HOST_IP=$(hostname -I | awk '{print $1}')
docker run -d --name pynode1 --gpus all -p 5001:5000 -e HOST_IP=$HOST_IP pynode:latest

# Instance 2
docker run -d --name pynode2 --gpus all -p 5002:5000 -e HOST_IP=$HOST_IP pynode:latest
```

### Resource Limits

Limit container resources:

```yaml
deploy:
  resources:
    limits:
      cpus: '4'
      memory: 8G
    reservations:
      memory: 4G
```

## Docker Hub

Pre-built images coming soon to Docker Hub.

## Security Considerations

- The default setup exposes port 5000 to your local network
- For production use, consider:
  - Adding authentication
  - Using HTTPS/TLS
  - Restricting network access with firewall rules
  - Running behind a reverse proxy (nginx, traefik)

## Best Practices

1. **Always set HOST_IP** before starting if using mDNS
2. **Use volumes** for persistent data (workflows, logs, models)
3. **Monitor GPU memory** when running multiple inference nodes
4. **Regular updates**: Rebuild images periodically for security patches
5. **Resource limits**: Set appropriate limits for your hardware

## Support

For issues and questions:
- GitHub Issues: [Your Repo URL]
- Documentation: See other files in `docs/` folder
- NVIDIA Container Toolkit: https://github.com/NVIDIA/nvidia-docker

## License

MIT License - See LICENSE file for details
