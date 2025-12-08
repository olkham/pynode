# Docker Setup for PyNode

## Prerequisites

- Docker Engine with GPU support (NVIDIA Container Toolkit)
- Docker Compose v1.28+ (for GPU support)
- NVIDIA GPU with CUDA support

## Quick Start

### Build and Run

```bash
docker-compose up --build
```

### Run in Background

```bash
docker-compose up -d
```

### View Logs

```bash
docker-compose logs -f
```

### Stop the Application

```bash
docker-compose down
```

## Configuration

### Ports

The application runs on port `5000` by default. To change the port, edit `docker-compose.yml`:

```yaml
ports:
  - "8080:5000"  # Change 8080 to your desired port
```

### GPU Support

The Docker Compose file is configured to use all available NVIDIA GPUs. To limit GPU access:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          device_ids: ['0']  # Use only GPU 0
          capabilities: [gpu]
```

### Persistent Storage

The following directories are mounted for persistence:
- `./workflows` - Saved workflows
- `./logs` - Application logs

## Building

### Custom CUDA Version

To use a different CUDA version, edit the `Dockerfile`:

```dockerfile
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04  # Change CUDA version
```

### Without GPU Support

For CPU-only deployment, use the CPU Dockerfile:

```bash
docker build -f Dockerfile.cpu -t pynode-cpu .
docker run -p 5000:5000 pynode-cpu
```

## Accessing the Application

Once running, access the web interface at:
- http://localhost:5000

## Troubleshooting

### GPU Not Detected

Verify NVIDIA Container Toolkit is installed:
```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

### Permission Issues

Ensure the mounted directories have proper permissions:
```bash
mkdir -p workflows logs
chmod 777 workflows logs
```

### Rebuild from Scratch

```bash
docker-compose down
docker-compose build --no-cache
docker-compose up
```
