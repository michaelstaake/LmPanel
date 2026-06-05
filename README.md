# LmPanel

LmPanel turns your GPUs (or CPU) into a flexible, intuitive AI server. It features a clean web interface and a fully OpenAI-compatible API that's ready to integrate with your workflow - all running via Docker on Ubuntu 26.04. Pretty much any GGUF AI model will work - whether you want to run a small model on your laptop or want to run a massive model on a high end PC with multiple video cards, LmPanel makes it simple to get started self-hosting LLMs.

It supports x86_64 CPUs, NVIDIA GPUs, AMD GPUs, and Intel Arc GPUs. You can have multiple cards and even mix multiple devices in the same setup. You can also pool multiple GPUs (within the same vendor) to run larger models. LmPanel is easy, private, and free.

## System Requirements

### Supported Devices

- **CPU**: x86_64
- **NVIDIA GPU**: CUDA (`--profile nvidia`)
- **AMD GPU**: Vulkan (`--profile vulkan`, recommended) or ROCm (`--profile rocm`, experimental — only if you are willing to troubleshoot known issues)
- **Intel Arc GPU**: Vulkan (`--profile vulkan`)

### Ubuntu 26.04

If it works on other operating systems, cool, but supporting that is outside the scope of this project. Ensure the correct GPU drivers and necessary extras (e.g., NVIDIA Container Toolkit) for your hardware are installed.

**If you are running Windows, that's OK - LmPanel works in WSL!** 

### Docker

Ensure Docker is installed and running in the system context and is using the correct runtimes for your hardware.

### Quick Start

**1. Clone or download the repository.**

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

The base stack always includes the CPU inference runtime. Add one or more GPU profiles depending on the hardware in the host. You can mix multiple hardware types.

Choose one of these commands:

#### CPU:

```bash
docker compose up -d --build
```

#### CPU + NVIDIA:

```bash
docker compose --profile nvidia up -d --build
```

#### CPU + Vulkan (Intel Arc, or AMD — recommended):

```bash
docker compose --profile vulkan up -d --build
```

#### CPU + ROCm (AMD discrete / AI Pro — experimental):

ROCm support is available but currently buggy. Use Vulkan for AMD GPUs unless you specifically need ROCm and are willing to troubleshoot driver, offload, and pool issues.

```bash
docker compose --profile rocm up -d --build
```

On the host, install ROCm user-space (Ubuntu 26.04 ships an older ROCm; for Radeon AI PRO R9700 and other recent AMD GPUs use ROCm 7.2+ from AMD’s repo with `amdgpu-install -y --usecase=rocm --no-dkms`). Add your user to the `render` and `video` groups. The `inference-rocm` service runs **privileged** so HIP can open `/dev/kfd` inside Docker (without this, `rocminfo` may report `Unable to open /dev/kfd read-write` and llama-server loads with 0 GPU layers).

Optional build args for `inference-rocm`: `ROCM_DEV_IMAGE` (defaults to `rocm/dev-ubuntu-24.04:7.2.3-complete`, which includes hipBLAS), `AMDGPU_TARGETS` (defaults to `gfx1200;gfx1201` for RDNA4 / R9700 and RX 9070-class GPUs; change in `.env` for other AMD archs), and `GGML_HIP_RCCL=ON` for experimental tensor-parallel pools.

If a model shows on a GPU in Status but VRAM stays near empty and tokens/sec is slow, llama.cpp likely loaded with **0 GPU layers** (CPU-only). LmPanel now passes `--fit off` by default (`LLAMA_FIT_TO_VRAM=false`) so large context lengths do not silently disable offload. Also check the model’s **GPU layers** setting (-1 = all), lower **context length** if VRAM is tight, and inspect `./logs/llama-<model_id>.log` for `offloaded N/N layers to GPU`.

#### CPU + NVIDIA + Vulkan + ROCm (mixed vendors):

```bash
docker compose --profile nvidia --profile vulkan --profile rocm up -d --build
```

When the ROCm profile is running, AMD GPUs are listed only as `rocm` devices (Vulkan no longer duplicates them). Intel Arc stays on Vulkan; NVIDIA stays on CUDA.

On startup (and whenever the Devices page refreshes), GPUs that are no longer reported by any running inference runtime are **removed from the database**, not left disabled. For example, switching from `--profile vulkan` to `--profile rocm` drops stale Vulkan rows; bringing the Vulkan profile back re-detects and re-adds them. Models pinned to removed devices revert to Auto assignment.

The initial build process may take a while depending on your environment and host performance, as we are building llama-cpp based on your chosen inference runtime.

Large models can also take several minutes to finish loading the first time they are activated during startup. If Docker marks the backend or inference containers unhealthy too early, increase `LLAMA_STARTUP_TIMEOUT_SECONDS` and the `STARTUP_HEALTHCHECK_*` values in `.env`.

**4. Proceed to web interface**

Once Docker reports the containers are healthy and started, open the LmPanel web interface: https://localhost:8443 or replace localhost with your server's local IP. You will receive an SSL error since LmPanel generates a self-signed SSL certificate. It is safe to bypass this error.

On a new install you will be redirected to the setup page where you can create your first admin account.

**5. Configure devices and pools**

Once your admin account is created, go to the Devices page and configure your inference devices.

If you have multiple GPUs of the same vendor, you can create a pool, which allows you to run larger models than would fit on a single GPU. Please note that once a GPU is in a pool, it can not be used on an individual basis until you remove it from the pool.

**6. Configure models**

Go to the Models page to configure your AI models. Models must be in GGUF format.

By default, models are in Auto mode for device selection. In this case, LmPanel will attempt to run the model on the most logical device or pool. However, if you want to pin a model to a specific device or pool, you may do so. Please ensure the device or pool has sufficient memory for the size of model you are running. Remember that the actual memory usage of a model may be higher than its file size, due to overhead, context, KV cache, etc.

**7. ENJOY!**

To stop LmPanel, use the command that matches the profiles you started with to ensure that all relevant containers are stopped. Docker Compose only stops services in the currently supplied profile set, so the `down` command must use the same profiles as `up`.

```bash
docker compose down
docker compose --profile nvidia down
docker compose --profile vulkan down
docker compose --profile rocm down
docker compose --profile nvidia --profile vulkan --profile rocm down
```

**Multi-GPU AMD pools (ROCm only):** if you run the ROCm profile, create a pool with vendor `rocm` and try split mode `layer` first. `tensor` mode is experimental; rebuild with `GGML_HIP_RCCL=ON` if you want to test it. PCIe bandwidth (e.g. PCIe 3.0) still limits cross-GPU performance. For most AMD setups, Vulkan is the more reliable path.

If you see garbled/random output only on ROCm pools (while single-GPU ROCm is fine), keep `ROCM_POOL_PARALLEL=1` and `ROCM_POOL_CACHE_RAM_MB=0` (the defaults), keep `ROCM_POOL_FLASH_ATTN_ENABLED=false`, and keep `ROCM_POOL_ALLOW_TENSOR_SPLIT=false` unless you have validated your exact stack.

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

Set `OPENAI_API_AUTH_REQUIRED=false` to allow anonymous chat completions (not recommended). Set `OPENAI_MODELS_AUTH_REQUIRED=true` if you want model listing to require the same JWT or API key as chat.

LmPanel currently supports `/v1/models` and `/v1/chat/completions`.

## Example API Call

```bash
curl -k https://localhost:8444/v1/chat/completions \
  -H "Authorization: Bearer API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-alias",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

### Example Vision API Call

```bash
curl -k https://localhost:8444/v1/chat/completions \
  -H "Authorization: Bearer API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-vision-model-alias",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "What is in this image?"},
          {
            "type": "image_url",
            "image_url": {
              "url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ..."
            }
          }
        ]
      }
    ],
    "stream": false
  }'
```

## OpenCode Config Example

Use this in your OpenCode config file to connect to LmPanel's OpenAI-compatible endpoint. With default auth settings, clients can call `/v1/models` without an API key; `apiKey` is still required for `/v1/chat/completions`. If `OPENAI_API_AUTH_REQUIRED=false`, apiKey is optional for chat as well and can be omitted or set to any placeholder value.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "lmpanel": {
      "name": "lmpanel",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://localhost:8444/v1",
        "apiKey": "API_KEY",
        "timeout": 7200000
      },
      "models": {
        "ai-model": {
          "name": "AI Model"
        }
      }
    }
  }
}
```

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
  - Version 1.0.0 requires a clean install — upgrades from Pawpile are not supported.

- **Backend or inference container turns unhealthy while loading a large model**:
  - Increase `LLAMA_STARTUP_TIMEOUT_SECONDS` in `.env`
  - Increase one or more `STARTUP_HEALTHCHECK_*` values in `.env` so Docker waits longer before marking the service unhealthy

- **Docker Desktop**:
  - While Ubuntu Server 26.04 is the recommended OS, LmPanel runs great on  Ubuntu Desktop 26.04. However, if you have Docker Desktop installed, and attempt to run LmPanel using the Docker Desktop system context, it will not be able to use all the system resources like RAM and GPUs.
  - Run `docker context use default` to correct the system context.


### Device Detection Issues

- **Device not detected**:
  - Check vendor tooling is installed on the host system:
    - Ubuntu 26.04: `nvidia-smi` (NVIDIA), `vulkaninfo` (Intel Arc / AMD — recommended), or `rocm-smi` (AMD with ROCm profile, experimental)
  - Ensure the appropriate GPU Docker runtime is configured and accessible to the environment.
  - Restart the application after installing drivers on the host.

- **Intel Arc (Vulkan) shows on the status page but memory is N/A or missing from AI Memory**:
  - VRAM totals come from `vulkaninfo` inside the `lmpanel-inference-vulkan` container (not the backend container).
  - Verify the inference container sees device-local heaps:
    ```bash
    docker exec lmpanel-inference-vulkan vulkaninfo 2>/dev/null | grep -E 'GPU[0-9]+:|memoryHeaps|DEVICE_LOCAL|size =|usage =' | head -80
    docker exec lmpanel-inference-vulkan curl -s http://localhost:8100/runtime/status | jq '.devices[] | select(.hardware_id|startswith("vulkan")) | {hardware_id, memory_total_mb, memory_used_mb, memory_source}'
    ```
  - `memory_total_mb` should be roughly your card's VRAM (e.g. ~6144 for a 6 GB Arc A380). If it is 0, check that `/dev/dri` is passed through and the host has a working Intel GPU driver.
  - **Used VRAM much lower than nvtop:** Intel Arc used memory comes from the kernel DRM/fdinfo path (`memory_source` `drm-xe` or `fdinfo`), not vulkaninfo alone. Rebuild `inference-vulkan` after updates. The compose profile adds `CAP_PERFMON` so the xe driver can report device-wide usage; without it, per-process fdinfo totals are still used when available.

## Need Help?

[Documentation on GitHub Wiki](https://github.com/michaelstaake/LmPanel/wiki)
[Report Problems on GitHub Issues](https://github.com/michaelstaake/LmPanel/issues)

## License

GPL-3.0 license

---

LmPanel was formerly known as Pawpile.
