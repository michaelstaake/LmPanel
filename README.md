# LmPanel

A panel for self-hosting LLMs but with one less L in the name because that's easier to say. 

LmPanel turns your GPUs (or CPU) into a flexible, intuitive AI server. Built around llama-cpp, LmPanel features a clean web interface and a fully OpenAI-compatible API that's ready to integrate with your workflow - all running via Docker on Ubuntu 26.04. Pretty much any GGUF AI model will work - whether you want to run a small model on CPU or a large model on a high-end workstation with multiple discrete video cards, LmPanel makes it simple to get started self-hosting LLMs.

It supports x86_64 CPUs, discrete AMD GPUs, and discrete Intel Arc GPUs. You can have multiple cards and even mix multiple devices in the same setup. You can also pool multiple GPUs (within the same vendor) to run larger models. NVIDIA GPUs and integrated/shared-RAM iGPUs (AMD APUs, Intel laptop graphics) are not supported.

LmPanel is easy, private, and free. Say goodbye to token costs and usage limitations! The only limitation with LmPanel is your hardware, but that's something you can control.

## System Requirements

### Supported Devices

**VERSION 2.X DROPS SUPPORT FOR NVIDIA GPUS AS WELL AS INTEGRATED AMD/INTEL GPUS. DO NOT UPDATE PAST 1.X IF YOU ARE USING NVIDIA GPUS OR INTEGRATED GRAPHICS.**

- **Supported:** x86_64 CPU inference.
- **Supported:** Discrete AMD GPUs through Vulkan.
- **Supported:** Discrete Intel Arc GPUs through Vulkan.
- **Not supported in 2.x:** NVIDIA GPUs.
- **Not supported in 2.x:** Integrated/shared-memory AMD and Intel GPUs, including APUs and laptop iGPUs.

Unsupported GPUs are soft-disabled: discovery ignores them rather than preventing LmPanel from starting. They cannot be selected for inference, but CPU and supported discrete GPUs on the same host remain available.

### Ubuntu 26.04

If it works on other operating systems, cool, but supporting that is outside the scope of this project.

**If you are running Windows, that's OK - LmPanel works in WSL!** 

### Docker

Ensure Docker is installed and running in the system context. AMD and Intel Arc GPUs use `/dev/dri` in the default Compose stack.

### Support Matrix

- **Supported host:** Ubuntu 26.04 on x86_64 with Docker Engine using the system/default context.
- **Supported deployment:** The repository's Docker Compose stack.
- **Supported accelerators:** Discrete AMD and Intel Arc GPUs with working host Vulkan drivers and `/dev/dri` access.
- **CPU fallback:** Available on every installation, but intended mainly for testing and fallback.
- **Best effort:** Ubuntu under WSL; GPU passthrough depends on the Windows, WSL, and Docker configuration.
- **Outside project support:** Other Linux distributions, Docker Desktop resource isolation, Kubernetes, ARM, NVIDIA, and integrated/shared-memory GPUs.

## Upgrading to 2.0

LmPanel 2.0 changes the supported device set and may apply database migrations at startup. Before upgrading from 1.x:

1. Confirm that the installation does not depend on NVIDIA or integrated graphics. Stay on 1.x if it does.
2. Stop the stack and make a complete backup using the procedure in [Backups and rollback](#backups-and-rollback).
3. Save the current release archive or Git revision and a copy of the current `.env`.
4. Review `.env.example`, especially the authentication, host port, timeout, and memory-limit settings.
5. Install the 2.0 release files, retain your `.env`, `models`, `certs`, and data backup, then validate the Compose configuration:

   ```bash
   docker compose config --quiet
   docker compose up -d --build
   docker compose ps
   ```

6. Check backend and inference logs, sign in, verify device discovery, and activate a small model before returning the server to normal use.

Do not test an upgrade for the first time on the only copy of production data. Database migrations are forward operations; a code-only downgrade is not a complete rollback.

### Quick Start

**1. Download Latest Release**

The current release version is the most stable flavor of LmPanel. Download the latest release from the [Releases page](https://github.com/michaelstaake/LmPanel/releases) and extract the archive.

Alternately, you can clone the repository to get the latest development version. You'll get the latest improvements before they make it to the release version, but it may be unstable or buggy.

```bash
git clone https://github.com/michaelstaake/LmPanel.git
cd LmPanel
```

**2. Copy environment file.**

The default settings should work for most users, but feel free to explore it to see what customization is offered.

```bash
cp .env.example .env
```

**3. Run it.**

```bash
docker compose up -d --build
```

#### Notes

At every startup, LmPanel auto-detects applicable devices. Temporarily missing or removed GPUs are retained as unavailable so their pool and pin assignments can recover if they return. Unsupported GPU types are ignored.

The initial build may take a while depending on your environment and host performance, as llama.cpp is compiled with Vulkan support. This is normal. Subsequent builds should be much quicker, although occasionally updates may require a fresh build of llama.cpp.

By default, every clean inference-image build clones the latest llama.cpp master branch available at build time. This intentionally provides current Vulkan fixes, but two builds of the same LmPanel release can therefore contain different llama.cpp revisions. The exact built commit remains recorded in `/opt/llama.cpp/BUILD_COMMIT`, and the detected tag/description is in `/opt/llama.cpp/BUILD_TAG`:

```bash
docker compose exec inference cat /opt/llama.cpp/BUILD_COMMIT
docker compose exec inference cat /opt/llama.cpp/BUILD_TAG
```

The release is also shown in LmPanel's status metadata and as a tooltip on the version shown in Settings. For a controlled build, set `LLAMA_CPP_TAG` in `.env` to a known upstream tag before rebuilding. Leave it unset to retain the latest-master behavior.

**4. Proceed to web interface**

Once Docker reports the containers are healthy and started, open the LmPanel web interface: https://localhost:8443 or replace localhost with your server's local IP. You will receive an SSL error since LmPanel generates a self-signed SSL certificate. It is safe to bypass this error.

On a new install you will be redirected to the setup page where you can create your first admin account. Setup through the frontend requires the one-time token printed in the backend startup logs (or the `SETUP_TOKEN` value from `.env`):

```bash
docker compose logs backend
```

**5. Configure devices and pools**

Once your admin account is created, go to the Devices page and configure your inference devices.

If you have multiple GPUs of the same vendor, you can create a pool, which allows you to run larger models than would fit on a single GPU. Please note that once a GPU is in a pool, it can not be used on an individual basis until you remove it from the pool.

**6. Configure models**

Go to the Models page to configure your AI models. Models must be in GGUF format.

By default, models are in Auto mode for device selection. In this case, LmPanel will attempt to run the model on the most logical device or pool. However, if you want to pin a model to a specific device or pool, you may do so. Please ensure the device or pool has sufficient memory for the size of model you are running. Remember that the actual memory usage of a model may be higher than its file size, due to overhead, context, KV cache, etc.

**7. ENJOY!**

To stop LmPanel:

```bash
docker compose down
```

## Network Ports

- `8443/tcp` is the default public web interface and same-origin API proxy (`FRONTEND_PORT`).
- `8444/tcp` is the default loopback-only direct backend/OpenAI-compatible API port (`BACKEND_PORT`).
- `443/tcp` is the frontend container's internal HTTPS port.
- `8000/tcp` is the backend container's internal HTTPS port.
- `8100/tcp` is the inference service's internal Compose-network port and is not published to the host.

Change host mappings with `FRONTEND_PORT` and `BACKEND_PORT` in `.env`. The default Compose file binds the backend port to `127.0.0.1`; use the frontend's same-origin `/v1/` proxy for remote clients. Do not expose port 8100 or the Docker control service to untrusted networks.

## Security Setup

Complete these steps before exposing LmPanel beyond a trusted local network:

1. LmPanel replaces an empty or `change-me` JWT secret with a random value persisted at `/app/data/.jwt-secret`. To manage it explicitly, set `JWT_SECRET` to at least 32 characters (for example, `openssl rand -hex 32`). Changing it invalidates existing sessions.
2. Keep `OPENAI_API_AUTH_REQUIRED=true`, issue separate API keys to clients, and set `OPENAI_MODELS_AUTH_REQUIRED=true` if model names must not be public.
3. Use a trusted certificate as described in [Custom SSL](#custom-ssl-lets-encrypt--cloudflare), or terminate TLS at a maintained reverse proxy. Treat the generated self-signed certificate as local bootstrap only.
4. Keep brute-force protection enabled. Configure Cloudflare Turnstile in **Settings → Security** when login or registration is internet-accessible.
5. Keep Docker and host packages patched, limit inbound access to required ports, and avoid running the stack through a resource-restricted Docker Desktop context.
6. Set random `INFERENCE_SHARED_SECRET` and `DOCKER_CONTROL_SECRET` values for defense in depth between containers.
7. Protect `.env`, `certs`, backups, and API keys. Only the allowlisted Docker control sidecar receives the Docker socket; it exposes container logs and frontend certificate reload, not the raw Docker API.

## Backups and Rollback

The database is stored in the Compose-managed `lmpanel-data` volume. Models, certificates, and logs are bind-mounted from `./models`, `./certs`, and `./logs`; configuration is in `.env`.

For a consistent backup, stop writes and copy all state:

```bash
docker compose stop
mkdir -p backup
docker compose cp backend:/app/data ./backup/data
cp -a .env models certs logs backup/
docker compose start
```

Store the backup away from the LmPanel host and test restoration periodically. Model files can be omitted only if they are reproducibly available elsewhere.

To roll back after a failed upgrade, stop the stack, restore the previous release files and `.env`, remove the upgraded `lmpanel-data` volume only after confirming the backup, recreate the volume through Compose, and copy the backed-up `/app/data` into the backend container. Restore `models` and `certs`, then rebuild the previous release. Never run older application code against a database already migrated by a newer release.

## Interacting with the AI Models

### Web Interface Chat

You can chat with your enabled models through the web interface.

### OpenAI-Compatible API

The API is the recommended way to use LmPanel through integrations with other software and platforms. LmPanel's API is OpenAI-Compatible, so you can easily integrate it into your workflow and applications.

By default, an API key is required for chat completions. Model listing is public by default so clients can discover available models before authenticating.

| Setting | Endpoint | Default |
|---------|----------|---------|
| `OPENAI_API_AUTH_REQUIRED` | `/v1/chat/completions` | `true` |
| `OPENAI_MODELS_AUTH_REQUIRED` | `/v1/models` | `false` |

Set `OPENAI_API_AUTH_REQUIRED=false` to allow anonymous chat completions (not recommended). Set `OPENAI_MODELS_AUTH_REQUIRED=true` if you want model listing to require authentication.

LmPanel currently supports `/v1/models`, `/v1/chat/completions`, and `/v1/usage/{timeframe}`.

## Example API Call

```bash
curl -k https://localhost:8443/v1/chat/completions \
  -H "Authorization: Bearer API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-alias",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

### Token usage

Token usage is tracked per API key for requests authenticated with that key. Query totals for a timeframe with:

```bash
curl -k https://localhost:8443/v1/usage/24h \
  -H "Authorization: Bearer API_KEY"
```

Allowed timeframes: `60m`, `24h`, `7d`, `30d`. The response includes `total_tokens` for that API key in the selected window.

## Custom SSL (Let's Encrypt + Cloudflare)

LmPanel can replace the default self-signed certificate with a trusted Let's Encrypt certificate using **Cloudflare DNS-01** validation. This works on homelab setups that use **custom HTTPS ports** or cannot bind host port 80, because validation happens through Cloudflare DNS—not through HTTP on LmPanel.

1. Add your hostname to a **Cloudflare** zone (proxied or DNS-only).
2. Create a Cloudflare **API token** with **Zone → DNS → Edit** for that zone.
3. In **Settings → Configuration**, set **URL** to your public address, e.g. `https://lmpanel.example.com` (no port, no trailing slash).
4. In **Settings → SSL**, save your Let's Encrypt account email and Cloudflare API token, then click **Obtain certificate**.
5. Point your reverse proxy at LmPanel's HTTPS port (for example `8443` in the default Docker compose mapping).

Optional environment variables in `.env` (see `.env.example`):

- `CLOUDFLARE_API_TOKEN` — overrides the token stored in the UI
- `LETSENCRYPT_EMAIL` — overrides the email stored in the UI
- `LETSENCRYPT_USE_STAGING=true` — use Let's Encrypt staging while testing
- `DOCKER_FRONTEND_CONTAINER` / `DOCKER_BACKEND_CONTAINER` — container names for nginx reload and backend restart after cert install

Certificates are stored in `./certs` and renewed automatically when they are within 30 days of expiry.

## Troubleshooting

### Docker Issues

- **Docker permission denied**:
  ```bash
  sudo usermod -aG docker $USER
  # Log out and back in, or use: newgrp docker
  ```

- **Docker image build fails**:
  - Check available disk space
  - Run `docker system prune` to clean up old images

- **Backend container is unhealthy after an update**:
  - Inspect `docker logs lmpanel-backend` for migration errors

- **Docker Desktop**:
  - While Ubuntu Server 26.04 is the recommended OS, LmPanel works on Ubuntu Desktop 26.04 as well. However, if you have Docker Desktop installed, and attempt to run LmPanel using the Docker Desktop system context, it will not be able to use all the system resources like RAM and GPUs.
  - Run `docker context use default` to correct the system context.


### Device Issues

- **Device not detected**:
  - Ensure host GPU drivers are installed and restart the system after driver changes.
  - Check that `vulkaninfo` works on the host and lists your discrete AMD or Intel Arc GPU(s).
  - NVIDIA GPUs and integrated/shared-RAM iGPUs are intentionally ignored.
  - After driver changes, recreate inference: `docker compose up -d --build --force-recreate inference` and `docker compose restart backend`.
  - If `vulkaninfo --summary` only lists `llvmpipe` or `lavapipe`, fix host Mesa/Vulkan drivers, then recreate inference. Run `bash scripts/verify-gpu-passthrough.sh` for a full diagnostic report.


### Performance Issues

First off, if you are using the CPU device, yes, it's probably going to be slow. CPU inference is included in all installs of LmPanel for testing and fallback purposes, but you'll probably want to use GPUs to actually run your inference workloads. CPUs simply aren't optimized for AI workloads.

If CPU load is high even though your models should be running on the GPU, ensure the GPU layer settings for the models are set to 99 (the default).

#### GPU stats

Nvtop is a useful tool you run on your host to see GPU stats. You can install it with:

```bash
sudo apt install nvtop -y
```

Run an AI model and check the stats while it's working.

If your GPU is maxed out on power usage and GPU load, you might just be at the limits of your chosen hardware. Note: As of the time of this writing, nvtop does not reliably show Intel Arc GPU load.

However, if your GPU's power usage and/or GPU load is not nearly maxed out while under load, you may have a bottleneck elsewhere in the system or need to tweak your configuration.

#### Check PCI-Express version and lanes.

In Nvtop, this is displayed as PCIe GEN 3@16x (for example).

Note: Some devices may fall back to a slower PCI-E speed at idle. This is normal, so ensure the GPU is under load before you start troubleshooting.

If you're using a GPU individually, PCI-E speeds don't matter too much, but if you are using the GPU Pools feature, PCI-E speeds can make a big difference.

The two things that matter for PCI-E speed is the version and the number of active lanes.
- It's like a highway - if you are trying to move X amount of cars, you can either add more lanes or the cars can drive faster.
- Each version of PCI-Express doubles the available bandwidth per lane.
- Most GPUs should be on an x16 bus, although some GPUs run on x8.
- Older platforms use older PCI-E versions.
- Consumer platforms and/or cheaper motherboards may have plenty of physical x16 slots, but typically only the "primary" PCI-E slot will be actually wired at x16, and subsequent slots will be electrically limited to x8, x4, or x1. Sometimes you can see this if you look in the slot - the additional contacts may not be present, but this is not a reliable indicator as just because the contacts are there doesn't mean your platform and CPU can actually use all those lanes.

#### Tweak Model Settings

Experiment with settings like flash attention and the other settings available in the UI.

#### Tweak Pool Settings

You can try different types of model distribution when using GPU Pools — **layer** and **tensor**.

With **layer** split (the default), each GPU takes turns during token generation. Alternating ~50% utilization per GPU in tools like `nvtop` is normal — GPUs do not run concurrently for single-stream decode. Pools primarily add **VRAM capacity** and **prompt-processing (prefill) throughput**; decode can be slightly slower than a single GPU on the Vulkan backend ([llama.cpp #16767](https://github.com/ggml-org/llama.cpp/issues/16767)).

For faster prompt processing on pooled models, open the model's **Advanced** settings and try **uBatch 2048** with **batch 16384** (increases VRAM use). LmPanel applies those defaults automatically when activating on a pool if the model does not set batch sizes.

**Large models + long context:** A 256k context window reserves a very large KV cache and is often the reason decode is slow. For everyday chat, set **Custom context 32768 or 65536**. When context is ≥ 8k, LmPanel auto-applies `--cache-type-k q8_0 --cache-type-v q8_0` on Vulkan (except tensor split) unless the model overrides cache types.

**Decode speed:** If your model fits on one GPU, pin it to that GPU (or use **Auto** assignment) instead of the pool. Layer-split pools trade decode speed for combined VRAM — ~15 tok/s on dual R9700s is typical for large models that genuinely need both cards. For models that fit on a single 32 GB card, LmPanel now prefers one GPU automatically.

**Tensor** split is experimental and requires a recent llama.cpp build (leave `LLAMA_CPP_TAG` unset or pin to current master). LmPanel auto-enables flash attention for Vulkan and when a pool uses tensor split. Tensor split can improve token-generation scaling on fast GPU interconnects; try layer first for compatibility.

The inference container sets `RADV_PERFTEST=nogttspill` by default, which avoids a common RADV GTT-spill slowdown on AMD during long-context decode.

## Need Help?

[Documentation on GitHub Wiki](https://github.com/michaelstaake/LmPanel/wiki)
[Report Problems on GitHub Issues](https://github.com/michaelstaake/LmPanel/issues)

## License

GPL-3.0 license
