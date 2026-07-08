# Dual AMD R9700 (RDNA4 / gfx1201) — LmPanel Vulkan/RADV Tuning Checklist

This guide targets a host with **two AMD R9700** cards (32 GB VRAM each, 64 GB host RAM) running LmPanel on the **Vulkan/RADV** backend (no ROCm).

## BIOS and PCIe

- [ ] **Above 4G Decoding** enabled
- [ ] **Resizable BAR** enabled for both GPUs
- [ ] Both GPUs in **CPU-attached** PCIe slots (not chipset lanes behind a single narrow link)
- [ ] **ASPM** disabled for GPU slots if you see link power-state hangs under load

## Kernel and firmware

- [ ] Recent kernel with **gfx1201** support (check `dmesg | grep gfx1201`)
- [ ] Up-to-date **linux-firmware** package
- [ ] Kernel parameters (example `/etc/default/grub`):

  ```
  amdgpu.gpu_recovery=1
  amdgpu.lockup_timeout=10000
  iommu=pt
  ```

- [ ] Rebuild initramfs and reboot after changes

## Host memory hygiene

- [ ] **Swap** or **zram** configured as a shock absorber (not primary inference memory)
- [ ] **earlyoom** or **systemd-oomd** enabled so runaway host RAM use is killed before lockup
- [ ] Inference container memory cap set (default in `docker-compose.yml`):

  ```env
  INFERENCE_MEM_LIMIT=52g
  INFERENCE_MEMSWAP_LIMIT=52g
  ```

  On a 64 GB host, ~52 GB leaves headroom for the backend, frontend, and OS.

## LmPanel settings (recommended)

| Setting | Suggested value | Why |
|---------|-----------------|-----|
| `LLAMA_CPP_TAG` | Unset (latest master) | Default; pin only if you need a reproducible build for debugging |
| `VULKAN_FLASH_ATTENTION_DEFAULT` | `auto` (try `off` if hangs persist) | A/B test RADV FA on gfx1201 |
| `VRAM_KV_MB_PER_1K_TOKENS` | `80` (tune per model family) | Realistic pool preflight |
| `VRAM_HEADROOM_MB` | `1024` | Safety margin per GPU |
| `MODEL_ACTIVATION_MAX_GTT_USED_RATIO` | `0.85` | Reject loads when GTT spillover is high |
| `LLAMA_STREAM_STALL_TIMEOUT_SECONDS` | `120` | Kill wedged streams in ~2 min |
| `GPU_RESET_COOLDOWN_TICKS` | `2` | Avoid activation storms after device_lost |
| `POOL_PREFER_SINGLE_GPU_WHEN_FIT` | `true` | Best decode speed when one 32 GB card fits |
| Per-model **KV cache type** | `q8_0` for K/V on large models | Halves KV VRAM → more single-GPU fits |

### Context and batch sizing

- Prefer **conservative context** (e.g. 16k–32k) until bench numbers justify higher
- Large models that barely fit: set `cache_type_k` / `cache_type_v` to `q8_0` in the model config API
- Pool `batch_size` / `ubatch_size`: run `scripts/bench-llama.sh` before lowering defaults from 4096/512

## Monitoring during load

```bash
# GPU driver errors (run during model activation)
sudo dmesg -w | grep -iE 'amdgpu|ring|timeout|gtt'

# Container memory (should hit cgroup limit before host lockup)
docker stats lmpanel-inference

# Runtime status including GTT per device
curl -s http://localhost:8100/runtime/status | jq '.devices[] | {name, memory_used_mb, gtt_used_mb, gtt_total_mb}'
```

### Telling lockup types apart

| Symptom | Likely cause |
|---------|----------------|
| SSH/console frozen, `dmesg` shows `amdgpu` timeout / `ring` hang | **GPU hang** → kernel reset, use `GPU_RESET_COOLDOWN_TICKS` |
| System sluggish, swap thrashing, OOM killer in `journalctl` | **Host RAM thrash** → tighten `INFERENCE_MEM_LIMIT`, lower context, enable oomd |
| High `gtt_used_mb` in status, activation rejected | **VRAM spillover** → unload models or quantize KV cache |

## Benchmark workflow

Before changing defaults:

```bash
chmod +x scripts/bench-llama.sh
./scripts/bench-llama.sh ./models/<your-model>/<model>.gguf
```

Compare single-GPU vs layer-split vs tensor-split and FA on/off. Record tokens/sec in your bench markdown under `./logs/`.

## Chaos verification (optional)

1. `kill -9` llama-server PID inside inference container → watchdog should recover within one tick
2. `kill -STOP` llama-server during streaming → stall detector fires within ~`LLAMA_STREAM_STALL_TIMEOUT_SECONDS`
3. Fill host RAM during activation → `InsufficientHostRamError` or GTT guard rejection, not host lockup
4. After reproducible GPU reset → confirm watchdog waits `GPU_RESET_COOLDOWN_TICKS` healthy ticks before re-activation

## Rebuild after toolchain changes

```bash
./lmpanel up --build inference
```

Check inference logs on startup for `llama.cpp build commit` and `Vulkan driver version`.
