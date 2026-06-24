# LmPanel

A panel for self-hosting LLMs but with one less L in the name because that's easier to say. 

LmPanel turns your GPUs (or CPU) into a flexible, intuitive AI server. Built around llama-cpp, LmPanel features a clean web interface and a fully OpenAI-compatible API that's ready to integrate with your workflow - all running via Docker on Ubuntu 26.04. Pretty much any GGUF AI model will work - whether you want to run a small model on your laptop or want to run something more powerful on a high end PC with multiple video cards, LmPanel makes it simple to get started self-hosting LLMs.

It supports x86_64 CPUs, NVIDIA GPUs, AMD GPUs, and Intel Arc GPUs. You can have multiple cards and even mix multiple devices in the same setup. You can also pool multiple GPUs (within the same vendor) to run larger models.

LmPanel is easy, private, and free. Say goodbye to token costs and usage limitations! The only limitation with LmPanel is your hardware, but that's something you can control.

## System Requirements

### Supported Devices

- **CPU**: x86_64
- **GPU** (NVIDIA, AMD, Intel Arc): Vulkan

All devices are handled by the default Docker stack. No compose profiles are required.

### Ubuntu 26.04

If it works on other operating systems, cool, but supporting that is outside the scope of this project.

**If you are running Windows, that's OK - LmPanel works in WSL!** 

### Docker

Ensure Docker is installed and running in the system context. AMD and Intel Arc GPUs use `/dev/dri` in the default stack. **NVIDIA hosts** also need the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Use the included [`compose`](compose) script instead of `docker compose` directly — it auto-configures GPU passthrough before every command.

### Quick Start

**1. Download Latest Release**

The current release version is the most stable flavor of LmPanel. Download the latest release from the [Releases page](https://github.com/michaelstaake/LmPanel/releases) and extract the archive.

Alternately, you can clone the repository to get the latest development version. You'll get the latest improvements before they make it to the release version, but it may be unstable or buggy.

```bash
#Development version not recommended for production use
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
./compose up -d --build
```

The `compose` script detects NVIDIA, AMD, Intel, and CPU-only hosts automatically and writes `docker-compose.override.yml` when needed before starting Docker. After adding or removing an NVIDIA GPU, run `./compose up -d` again to refresh the configuration.

#### Notes

At every startup, LmPanel will auto-detect all applicable devices. If you remove or replace a GPU, any old ones will be removed from the database automatically. Models that were assigned to a specific device will revert to Auto mode.

The initial build may take a while depending on your environment and host performance, as llama.cpp is compiled with Vulkan support. This is normal. Subsequent builds should be much quicker, although occasionally updates may require a fresh build of llama.cpp.

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

To stop LmPanel:

```bash
./compose down
```

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
  - LmPanel ersion 1.0.0 requires a clean install — upgrades from Pawpile (the project LmPanel is based on) are not supported.

- **Docker Desktop**:
  - While Ubuntu Server 26.04 is the recommended OS, LmPanel runs great on  Ubuntu Desktop 26.04. However, if you have Docker Desktop installed, and attempt to run LmPanel using the Docker Desktop system context, it will not be able to use all the system resources like RAM and GPUs.
  - Run `docker context use default` to correct the system context.


### Device Issues

- **Device not detected**:
  - Check that `vulkaninfo` works on the host and lists your GPU(s).
  - On NVIDIA hosts, run `./compose up -d --build --force-recreate inference` and `./compose restart backend`. The `compose` script bind-mounts the host `nvidia_icd.json` and NVIDIA GL libraries when the container toolkit does not inject them automatically.
  - If `nvidia-smi` works inside the container but `vulkaninfo --summary` only lists `llvmpipe` or `lavapipe`, run `./compose up -d --build --force-recreate inference` again after fixing the host driver. Run `bash scripts/verify-gpu-passthrough.sh` for a full diagnostic report. You can also run `bash scripts/configure-gpu-compose.sh` manually to inspect GPU configuration.
  - Ensure host GPU drivers are installed and restart LmPanel after driver changes.

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

You can try different types of model distribution when using GPU Pools - layer and tensor.

## Need Help?

[Documentation on GitHub Wiki](https://github.com/michaelstaake/LmPanel/wiki)
[Report Problems on GitHub Issues](https://github.com/michaelstaake/LmPanel/issues)

## License

GPL-3.0 license

## Prior to 6/5/26, LmPanel was formerly known as Pawpile
