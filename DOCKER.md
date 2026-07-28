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

### Version

The version shown in the UI is derived automatically from git history during
the Docker build — no extra flags or environment variables are needed. Tagged
commits display a clean version (e.g. `v0.2.3`); untagged commits include the
distance and short SHA (e.g. `v0.2.3-1-gcd272cf`).

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

## mDNS / Service Discovery

### The Limitation

The default `docker-compose.yml` uses Docker's standard bridge network. mDNS
(multicast DNS) relies on link-local multicast traffic (UDP `224.0.0.251:5353`),
which the bridge network's NAT does not forward in either direction. With the
default compose file, PyNode's mDNS nodes can broadcast and listen *inside*
the container, but that traffic never reaches the LAN — so other machines on
your network cannot discover the container, and the container cannot discover
services running elsewhere.

### `HOST_IP`

The `HOST_IP` environment variable (see `docker-compose.yml`) only controls
the IP address **advertised** in mDNS service records - it does *not* make
multicast traffic reach the LAN. Setting `HOST_IP` without one of the fixes
below just means the (unreachable) mDNS records will advertise the right
address instead of the container's internal one; it does not fix discovery.

### Fixing It

**Option 1: `network_mode: host` (Linux hosts only, full fix)**

On Linux, host networking removes the network isolation between the
container and the host, so multicast works exactly as it would for a
process running directly on the host:

```yaml
services:
  pynode:
    network_mode: host
    # ports: mapping is ignored in host mode - the container shares the
    # host's network stack directly, so remove/comment out `ports:` above.
```

This does **not** work on Docker Desktop for Windows/macOS - Docker Desktop
runs containers inside a lightweight VM, and `network_mode: host` there still
does not bridge multicast across the VM boundary.

**Option 2: macvlan network**

A macvlan network gives the container its own IP address directly on the LAN
(as if it were a separate physical device), which also allows multicast to
work normally. This works on Docker Desktop as well as Linux, but requires
more setup (a dedicated IP, and typically a way for the host itself to reach
the container since macvlan interfaces are not reachable from the host by
default). See the
[Docker macvlan network documentation](https://docs.docker.com/network/drivers/macvlan/)
for setup details.

**Option 3: mDNS reflector on the host**

When host networking isn't available (e.g. Docker Desktop), run an mDNS
reflector on the host to bridge multicast between the host's network and the
container's bridge network:

- **avahi-daemon** (Linux) - enable reflection in `/etc/avahi/avahi-daemon.conf`:
  ```ini
  [reflector]
  enable-reflector=yes
  ```
- **mdns-repeater** - run as a sidecar/host process that repeats mDNS packets
  between interfaces.

This is the option that works when host networking isn't an option, at the
cost of an extra moving part to run and maintain.

### Port Matching

Whichever option you use, the port PyNode advertises in its mDNS records
must match the port other machines can actually reach it on (the *published*
port), not just the container's internal port. If you remap ports (e.g.
`"8080:5000"`), make sure discovery consumers connect using the published
port (`8080`), not the internal one.

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
