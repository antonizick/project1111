# P11 Benchmarks

**Last updated:** 2026-11-02 18:08 CST (Phase 03). Measured on the reference laptop by `scripts/bench/` against the pinned engine. Later phases append their own sections (Phase 05: adapter overhead; Phase 16: success criteria).

## Method
- **Engine:** headless ComfyUI v0.43.0 (`426f5eea52a7ece1dd599fff4cb6cd1f352ddd24`), uv CPython 3.12.15, torch 2.14.1+cu130, cuDNN 9.24, SDPA attention, UNet/text encoders fp16, VAE fp32 (ComfyUI's default on Turing). Launched by `scripts/bench/engine.py` with the flags in `engine/engine.lock.toml` (`--listen 127.0.0.1 --offline --disable-all-custom-nodes …`), core nodes only.
- **Harness:** `scripts/bench/run.py <stage>` (P11 uv env) takes the GPU lock (R24), switches the power profile to `performance` and restores it on exit (H8), starts and stops the engine, and talks to ComfyUI's HTTP/websocket API directly. VRAM, temperature, SM clock, power and throttle reasons are sampled with `nvidia-smi` every 200 ms (1 s in the thermal loop). One JSON per run (schema `scripts/bench/schema.py`, unit-tested). `scripts/bench/all.sh` runs the stages; `python -m scripts.bench.report` rebuilds these tables and the contact sheets.
- **Prompts:** 10 photoreal, 3 3D-avatar, 3 logo (`scripts/bench/prompts.py`; non-sexual, no real people), seeds 1111 / 424242 / 9001. Graph variants per run get distinct seeds so ComfyUI's node cache never skips the base pass.
- **Timings:** wall clock from queueing to the last output. *Cold* = first run after unloading models (weights from the page cache, not from a cold disk); *warm* = models resident. Peak VRAM is the GPU total including the desktop; "(engine)" subtracts the idle VRAM measured just before the engine started.
- **Upscale chains (ADR-0010):** `latent` = bislerp latent upscale to the target + hires KSampler (denoise 0.45, about half the base steps) + tiled VAE decode; `model` = VAE decode + 4×NomosWebPhoto RealPLKSR + Lanczos resize to the target; `both` = `model`, then tiled VAE encode + hires pass (denoise 0.3) + tiled decode. Generation bucket: SDXL 1344×768, SD 1.5 1024×576; avatars 896×1152 / 512×640.

## Machine state
HP Omen laptop, RTX 2070 with Max-Q Design (TU106BM, sm_75, 8192 MiB; ComfyUI sees 7767 MB), driver 615.78.08 (nvidia-open), kernel 7.2.8-9-omarchy, 31 GB RAM. Every stage ran on AC power with the `performance` profile (the machine's own profile, `power-saver`, was restored after each stage and is the current setting). Desktop VRAM before each engine start: 1065–1142 MiB (R5's "~1 GB" holds). Runs: 2026-11-02 15:39 to 18:06 CST.

## Candidates
All from login-free Hugging Face repos (H2), safetensors only (S4), pinned to a commit; the SHA-256 computed after download matched the repo's LFS SHA-256 for every file. Download total 31.2 GB (budget 100 GB, H1).

| Key | File (repo @ commit) | Size | Licence (commercial use) | Outcome |
|---|---|---:|---|---|
| realvisxl5_lightning | `RealVisXL_V5.0_Lightning_fp16.safetensors` (SG161222/RealVisXL_V5.0_Lightning @ f4454158) | 6.94 GB | OpenRAIL++-M (yes, use restrictions) | **default** |
| juggernautxl9 | `Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors` (RunDiffusion/Juggernaut-XL-v9 @ cf419233) | 7.11 GB | CreativeML OpenRAIL-M (yes, use restrictions) | **default (Quality model)** |
| realisticvision6 | `Realistic_Vision_V6.0_NV_B1_fp16.safetensors` (SG161222/Realistic_Vision_V6.0_B1_noVAE @ 9a857a69) | 2.13 GB | CreativeML OpenRAIL-M (yes, use restrictions) | full set (SD 1.5 low-VRAM) |
| realvisxl5 | `RealVisXL_V5.0_fp16.safetensors` (SG161222/RealVisXL_V5.0 @ ac93e0dd) | 6.94 GB | OpenRAIL++-M | rejected, deleted |
| dreamshaperxl_turbo | `DreamShaperXL_Turbo_v2_1.safetensors` (Lykon/dreamshaper-xl-v2-turbo @ f70ad5bc) | 6.94 GB | OpenRAIL++-M | rejected, deleted |
| juggernautxl9_lightning4 | `sdxl_lightning_4step_lora.safetensors` (ByteDance/SDXL-Lightning @ c9a24f48) on juggernautxl9 | 0.39 GB | OpenRAIL++-M | rejected, deleted |
| VAE (SDXL) | `sdxl_vae.safetensors` (madebyollin/sdxl-vae-fp16-fix @ 207b116d) | 0.33 GB | MIT | **default** |
| VAE (SD 1.5) | `vae-ft-mse-840000-ema-pruned.safetensors` (stabilityai/sd-vae-ft-mse-original @ 629b3ad3) | 0.33 GB | MIT | full set |
| upscaler | `4xNomosWebPhoto_RealPLKSR.safetensors` (Phips/4xNomosWebPhoto_RealPLKSR @ 49d5da19) | 0.03 GB | CC-BY-4.0 (yes, attribution) | **default** |
| upscaler | `4x-UltraSharp.safetensors` (Kim2091/UltraSharp @ 920fe218) | 0.07 GB | CC-BY-NC-SA-4.0 (**no**) | rejected, deleted |

SHA-256 values are in ADR-0018 and `~/.cache/p11/bench/candidates/candidates.json`. Sampler settings come from each model card (`scripts/bench/configs.py`). Not measured: a Forge-family engine (ComfyUI met every hard requirement, so H6 gave no reason to switch) and a quantized larger model (follow-up).

## Results: native bucket (16 prompts, 1344×768 / 1024×576)
| Model | Sampler | Steps | CFG | Cold s | Warm s (median) | it/s | Peak VRAM MiB (engine) | Peak RAM MiB | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dreamshaperxl_turbo | dpmpp_sde/karras | 6 | 2 | 22.5 | 18.7 | 0.45 | 7730 (6700) | 9080 | 0 |
| dreamshaperxl_turbo | dpmpp_sde/karras | 8 | 2 | n/a | 19.7 | 0.48 | 7720 (6690) | 9107 | 0 |
| juggernautxl9 | dpmpp_2m/karras | 30 | 4.5 | 42.4 | 38.6 | 0.93 | 7757 (6727) | 8955 | 0 |
| juggernautxl9 | dpmpp_2m/karras | 40 | 4.5 | n/a | 47.7 | 0.96 | 7718 (6688) | 8956 | 0 |
| juggernautxl9_lightning4 | euler/sgm_uniform | 4 | 1 | 15.8 | 6.5 | 2.09 | 7720 (6690) | 9193 | 0 |
| realisticvision6 | dpmpp_2m_sde/karras | 40 | 5 | n/a | 22.2 | 1.99 | 5549 (4519) | 4562 | 0 |
| realisticvision6 | dpmpp_sde/karras | 25 | 5 | 27.3 | 27.2 | 0.98 | 5502 (4472) | 4562 | 0 |
| realvisxl5 | dpmpp_2m/karras | 40 | 5 | n/a | 45.2 | 0.98 | 7745 (6715) | 8946 | 0 |
| realvisxl5 | dpmpp_sde/karras | 30 | 5 | 65.8 | 66.2 | 0.48 | 7745 (6715) | 8945 | 0 |
| realvisxl5_lightning | dpmpp_sde/karras | 5 | 1.5 | 21.6 | 13.7 | 0.49 | 7741 (6711) | 9010 | 0 |
| realvisxl5_lightning | dpmpp_sde/karras | 8 | 2 | n/a | 19.5 | 0.48 | 7727 (6697) | 9023 | 0 |

`it/s` counts sampler steps; DPM++ SDE runs two model evaluations per step, so it shows about half the rate of DPM++ 2M at equal cost per evaluation.

## Results: avatar (portrait bucket 896×1152)
At 16:9 the few-step models drew the avatar character twice (see the contact sheet), so avatars use a 4:5 portrait bucket, where every model drew one character.

| Model | Sampler | Steps | CFG | Cold s | Warm s (median) | it/s | Peak VRAM MiB (engine) | Peak RAM MiB | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dreamshaperxl_turbo | dpmpp_sde/karras | 6 | 2 | 20.0 | 14.8 | 0.49 | 7746 (6673) | 8965 | 0 |
| juggernautxl9 | dpmpp_2m/karras | 30 | 4.5 | 39.9 | 34.2 | 0.97 | 7746 (6673) | 8952 | 0 |
| realvisxl5 | dpmpp_2m/karras | 40 | 5 | 49.4 | 44.7 | 1.00 | 7746 (6673) | 8931 | 0 |
| realvisxl5_lightning | dpmpp_sde/karras | 5 | 1.5 | 17.9 | 12.3 | 0.50 | 7730 (6657) | 8924 | 0 |

## Results: wallpaper presets (prompt p01, dynamic VRAM)
| Model | VRAM mode | Preset | Chain | Seconds | Peak VRAM MiB (engine) | Result |
|---|---|---|---|---:|---:|---|
| dreamshaperxl_turbo | dynamic | 1920x1080 | both | 53.8 | 7710 (6568) | ok |
| dreamshaperxl_turbo | dynamic | 1920x1080 | latent (cold) | 45.8 | 7520 (6378) | ok |
| dreamshaperxl_turbo | dynamic | 1920x1080 | model | 19.2 | 7712 (6570) | ok |
| dreamshaperxl_turbo | dynamic | 2560x1440 | both | 90.1 | 7728 (6586) | ok |
| dreamshaperxl_turbo | dynamic | 2560x1440 | latent | 66.4 | 7678 (6536) | ok |
| dreamshaperxl_turbo | dynamic | 2560x1440 | model | 20.7 | 7728 (6586) | ok |
| juggernautxl9 | dynamic | 1920x1080 | both | 102.3 | 7720 (6578) | ok |
| juggernautxl9 | dynamic | 1920x1080 | latent (cold) | 90.4 | 7496 (6354) | ok |
| juggernautxl9 | dynamic | 1920x1080 | model | 40.8 | 7745 (6603) | ok |
| juggernautxl9 | dynamic | 2560x1440 | both | 161.7 | 7745 (6603) | ok |
| juggernautxl9 | dynamic | 2560x1440 | latent | 139.0 | 7678 (6536) | ok |
| juggernautxl9 | dynamic | 2560x1440 | model | 41.7 | 7725 (6583) | ok |
| juggernautxl9_lightning4 | dynamic | 1920x1080 | both | 39.4 | 7735 (6593) | ok |
| juggernautxl9_lightning4 | dynamic | 1920x1080 | latent (cold) | 30.4 | 7689 (6547) | ok |
| juggernautxl9_lightning4 | dynamic | 1920x1080 | model | 11.6 | 7722 (6580) | ok |
| juggernautxl9_lightning4 | dynamic | 2560x1440 | both | 60.2 | 7729 (6587) | ok |
| juggernautxl9_lightning4 | dynamic | 2560x1440 | latent | 37.1 | 7414 (6272) | ok |
| juggernautxl9_lightning4 | dynamic | 2560x1440 | model | 11.2 | 7744 (6602) | ok |
| realisticvision6 | dynamic | 1920x1080 | both | 141.9 | 6044 (4902) | ok |
| realisticvision6 | dynamic | 1920x1080 | latent (cold) | 131.9 | 4524 (3382) | ok |
| realisticvision6 | dynamic | 1920x1080 | model | 28.6 | 5885 (4743) | ok |
| realisticvision6 | dynamic | 2560x1440 | both | 327.5 | 5574 (4432) | ok |
| realisticvision6 | dynamic | 2560x1440 | latent | 311.9 | 5794 (4652) | ok |
| realisticvision6 | dynamic | 2560x1440 | model | 30.0 | 5526 (4384) | ok |
| realvisxl5 | dynamic | 1920x1080 | both | 182.4 | 7735 (6593) | ok |
| realvisxl5 | dynamic | 1920x1080 | latent (cold) | 162.2 | 7520 (6378) | ok |
| realvisxl5 | dynamic | 1920x1080 | model | 85.5 | 7700 (6558) | ok |
| realvisxl5 | dynamic | 2560x1440 | both | 281.6 | 7734 (6592) | ok |
| realvisxl5 | dynamic | 2560x1440 | latent | 253.5 | 7544 (6402) | ok |
| realvisxl5 | dynamic | 2560x1440 | model | 86.1 | 7738 (6596) | ok |
| realvisxl5_lightning | dynamic | 1920x1080 | both | 55.4 | 7735 (6593) | ok |
| realvisxl5_lightning | dynamic | 1920x1080 | latent (cold) | 45.3 | 7477 (6335) | ok |
| realvisxl5_lightning | dynamic | 1920x1080 | model | 18.3 | 7735 (6593) | ok |
| realvisxl5_lightning | dynamic | 2560x1440 | both | 88.2 | 7735 (6593) | ok |
| realvisxl5_lightning | dynamic | 2560x1440 | latent | 65.7 | 7735 (6593) | ok |
| realvisxl5_lightning | dynamic | 2560x1440 | model | 18.7 | 7735 (6593) | ok |

## Results: VRAM modes (RealVisXL Lightning, `model` chain)
`dynamic` = ComfyUI v0.43.0 default (dynamic VRAM); `classic` = `--disable-dynamic-vram`; `lowvram` = `--disable-dynamic-vram --lowvram`.

| Model | VRAM mode | Preset | Chain | Seconds | Peak VRAM MiB (engine) | Result |
|---|---|---|---|---:|---:|---|
| realvisxl5_lightning | classic | 1920x1080 | model | 21.2 | 6578 (5513) | ok |
| realvisxl5_lightning | classic | 1920x1080 | model | 20.4 | 6516 (5451) | ok |
| realvisxl5_lightning | classic | 2560x1440 | model | 20.5 | 6516 (5451) | ok |
| realvisxl5_lightning | classic | 2560x1440 | model | 20.5 | 6557 (5492) | ok |
| realvisxl5_lightning | classic | native | native | 14.7 | 6494 (5429) | ok |
| realvisxl5_lightning | classic | native | native (cold) | 19.9 | 6494 (5429) | ok |
| realvisxl5_lightning | dynamic | 1920x1080 | model | 18.3 | 7722 (6633) | ok |
| realvisxl5_lightning | dynamic | 1920x1080 | model | 18.2 | 7722 (6633) | ok |
| realvisxl5_lightning | dynamic | 2560x1440 | model | 18.6 | 7722 (6633) | ok |
| realvisxl5_lightning | dynamic | 2560x1440 | model | 18.6 | 7722 (6633) | ok |
| realvisxl5_lightning | dynamic | native | native | 13.9 | 7722 (6633) | ok |
| realvisxl5_lightning | dynamic | native | native (cold) | 19.2 | 7722 (6633) | ok |
| realvisxl5_lightning | lowvram | 1920x1080 | model | 19.8 | 6516 (5429) | ok |
| realvisxl5_lightning | lowvram | 1920x1080 | model | 20.4 | 6516 (5429) | ok |
| realvisxl5_lightning | lowvram | 2560x1440 | model | 20.8 | 6516 (5429) | ok |
| realvisxl5_lightning | lowvram | 2560x1440 | model | 20.6 | 6516 (5429) | ok |
| realvisxl5_lightning | lowvram | native | native | 14.6 | 6516 (5429) | ok |
| realvisxl5_lightning | lowvram | native | native (cold) | 17.8 | 6548 (5461) | ok |

Dynamic VRAM fills free VRAM with cached weights (peak ~7.7 GB total) and is the fastest; `lowvram` caps the peak at ~6.5 GB for ~10 % more time and is the OOM retry setting (ADR-0018).

## Stability (50 consecutive runs)
RealVisXL V5.0 Lightning, 2560×1440, `model` chain, dynamic VRAM, all 16 prompts in rotation: **50/50 succeeded, 0 OOM**. Time per image: median 17.7 s, mean 18.2 s, min 17.0 s, max 24.6 s (the cold first run 22.0 s). Peak VRAM 7663–7752 MiB total; GPU max 80 °C. Raw: `runs/stability/` and `runs/stability-summary-realvisxl5_lightning-dynamic-1793663766.json`.

## Thermals (10-minute loop)
Same combination at 1920×1080, back to back for 10 min directly after the stability run (heat-soaked start): 34 images (17.6 s each, no slowdown over the loop). Per-minute averages:

| Minute | Temp °C (avg / max) | SM clock MHz (avg / max) | Power W (avg / max) |
|---:|---|---|---|
| 0 | 77 / 79 | 1334 / 1770 | 64 / 75 |
| 2 | 78 / 79 | 1352 / 1770 | 69 / 82 |
| 4 | 79 / 79 | 1350 / 1770 | 68 / 76 |
| 6 | 79 / 79 | 1350 / 1770 | 69 / 79 |
| 8 | 79 / 79 | 1348 / 1770 | 68 / 78 |
| 9 | 78 / 79 | 1359 / 1770 | 68 / 80 |

The GPU is **power-limited, not thermally limited**: 90 % of samples report the software power cap (`0x4`), the rest an unnamed bit `0x400` or none; no thermal slowdown bit was set. Temperature plateaus at 78–79 °C. Owner question 5's default (pause at 87 °C, resume at 80 °C, H9) is never reached in single-image work; Phase 13 should re-check under the video job, which loads the GPU differently. Raw: `runs/thermal-realvisxl5_lightning-1793664377.json`.

## Engine adapter overhead (Phase 05)
Measured 2026-11-02 19:10–19:25 CST on the laptop (AC, `performance` profile, restored to `power-saver` afterwards; GPU lock held), `16:9-1920x1080` photoreal with RealVisXL V5.0 Lightning and the `model` chain, the same wall-clock definition as above (queue → engine reports success). Script: `scripts/bench/adapter.py`; raw JSON `~/.cache/p11/bench/adapter/20261102-191004.json`.

| Run order | Phase 03 bench client (median of 10) | `ComfyEngine` (median) | Overhead |
|---|---|---|---|
| bench client first, then 20 back-to-back adapter runs | 16.03 s | 16.59 s (n = 20, 16.36–17.14 s) | +3.5 % |
| adapter first (10 runs), then bench client | 16.67 s | 16.55 s (n = 10) | −0.7 % |

The difference follows the run order (the second block runs on a warmer GPU), so the adapter adds no measurable overhead; the worst case is inside the < 5 % target. Fetching the PNG through `/view` adds 0.01 s. 20/20 runs succeeded; peak VRAM 7.72 GB total (including the desktop), max 77 °C (NVML at 1 Hz, 369 samples). Engine start to ready: 5.6 s; first (cold) image 22.4 s. Interrupt during sampling: 0.52 s (3 of 3) from `interrupt()` to `EngineInterrupted` (limit 2 s). Warm times are ~2 s faster than Phase 03's 18.3 s: the Phase 03 figure was measured during the full bake-off, Phase 05 on a fresh session.

**Forced OOM.** Oversized latents do not fail on this card at v0.43.0 (3072² and 4096² exceeded a 240 s timeout; batch 8 at 1024² finished in 93 s), so the gpu tests force a real OOM with a helper process that leaves 600 MiB of VRAM free: `VAEDecode` raises a CUDA OOM, the retry in `--lowvram` succeeds when the pressure is relieved and otherwise ends in the plain-English error (ADR-0020).

## Network (S1)
`ss -ltnp` during the runs: ComfyUI listened only on `127.0.0.1:8188`. A watcher (`candidates/netwatch.sh`) recorded every socket of the engine process with a non-loopback peer once per second from 15:39 to 18:08 CST, across all stages: **none**.

## Inpainting (Phase 10, ADR-0025)
Measured 2026-11-03 05:18 CST on the laptop (power profile `performance` during the runs, restored to `power-saver`; AC power). Script: `scripts/bench/inpaint_tune.py` (`generate`, then `inpaint`), through the Studio API on the pinned engine with the default model (RealVisXL V5.0 Lightning, 5 steps, DPM++ SDE Karras, CFG 1.5, fp16-fix VAE). Ten P11-generated 1920×1080 sources (synthetic prompts, no personal photos): an elderly fisherman's face, hands on a mug, a red car, a bowl of apples, a lake sky, a dog's neck, a sofa, a pedestrian on a night street, a man's face in an office, a sea patch for a sailboat. Masks are ellipses over the region (`masks.json`), with a "what should be there" prompt per image. Each image ran two strengths per preset with crop on, plus one full-frame run (crop off, 0.6); seed 77; mask grow 8 px, blur 12 px, padding 48 px.

**Engine time per job (s)**, 1920×1080, crop on unless noted:

| Image | Subtle 0.3 | 0.4 | Change 0.55 | 0.65 | Replace 0.85 | 1.0 | Full frame (0.6) |
|---|---|---|---|---|---|---|---|
| fisherman | 19.7 | 10.9 | 11.0 | 11.3 | 11.2 | 11.6 | 30.8 |
| hands | 17.0 | 11.8 | 11.4 | 11.4 | 13.5 | 11.4 | 30.9 |
| car | 16.9 | 13.4 | 13.4 | 13.4 | 13.6 | 13.7 | 31.3 |
| apples | 14.7 | 11.6 | 11.6 | 11.6 | 11.7 | 11.7 | 31.3 |
| lake | 15.0 | 11.8 | 12.0 | 11.9 | 11.9 | 13.1 | 31.8 |
| dog | 14.9 | 11.9 | 11.8 | 12.7 | 11.9 | 11.8 | 32.0 |
| sofa | 15.2 | 11.9 | 11.9 | 11.9 | 11.9 | 11.9 | 31.7 |
| street | 14.8 | 11.7 | 11.7 | 11.7 | 11.7 | 11.9 | 31.9 |
| office | 14.9 | 11.8 | 11.7 | 11.8 | 11.9 | 11.7 | 31.7 |
| beach | 14.9 | 11.9 | 12.0 | 11.8 | 11.8 | 11.9 | 31.9 |

- 70/70 runs finished, **no OOM**; peak VRAM 7.7 GB (whole card, desktop included, dynamic VRAM), peak GPU temperature 77 °C. Crop runs: median 11.9 s engine / 13.8 s wall; full-frame runs: median 31.7 s (the 2 MP VAE encode/decode dominates). The first run on each new source is ~3 s slower (new image upload and encode cache; the fisherman's 19.7 s includes the cold model load).
- **Quality (by eye, contact grids `~/.cache/p11/bench/inpaint/grids/*.jpg`):** 0.3 is nearly a no-op; 0.4 refines texture (skin, fur, fingers) without changing shapes. 0.55 changes little; 0.65 changes material, expression and lighting while keeping the layout (apples partly become oranges, clouds appear, the fisherman smiles) but does not recolour a large object (the car stays red). 0.85 and 1.0 both replace the content (blue car, bowl of oranges, storm sky, a new face) and look alike; 0.85 keeps more of the surrounding light. A replaced face shows a soft seam at the blend band where skin tone differs; a larger mask blur or Change hides it. Full-frame at 0.6 barely touched small regions, so crop stays the default.
- **Picks:** Subtle fix **0.4**, Change **0.65**, Replace **0.85** (`presets.INPAINT_PRESETS`); mask blur 12 px, grow 8 px, padding 48 px, crop on, working size 1 MP (at most 4× upscale), cap 2560×1440. To recolour an object, use Replace or Advanced → Denoise ≈ 0.75–0.85.
- **Mask editor (Playwright, Chromium on the laptop):** 2560×1440 photo, one stroke of 241 pointer moves with a large brush: draw 0.24 ms average / 4.9 ms max per move; frames median and p95 16.7 ms (60 fps).
- **Acceptance gpu test** (`tests/gpu/test_inpaint_gpu.py`): each preset on a 1920×1080 result, pixels outside the blend band byte-identical, child in the gallery, a template saved with the mask kept re-runs.

## Background replacement (Phase 11, ADR-0026, ADR-0027)
Measured 2026-11-03 on the laptop. Script: `scripts/bench/background_tune.py` (`subjects`, `segment`, `composite`, `harmonize`), material in `~/.cache/p11/bench/background/` (not in git). The ten P11-generated 1024x1024 subjects (fixed seeds 2100+, synthetic prompts, no personal photos): four portraits and six products (mug, sneakers, plant, laptop, statue, chair); the ten backgrounds are the Phase 10 source photos. Segmentation and compositing run on the CPU (ADR-0026); the harmonize runs through the Studio API on the pinned engine (power profile `performance` during them, restored to `power-saver`; AC power).

**Segmentation (CPU, i7-9750H, six ONNX threads, 1024x1024 input):**

| Model | File | Mean s | Min s | Max s | Masks vs `birefnet-lite` (IoU mean / min) |
|---|---|---|---|---|---|
| `birefnet-lite` (default) | 224 MB | 9.7 | 8.7 | 11.9 | 1.000 |
| `birefnet` (full) | 973 MB | 19.7 | 17.9 | 25.1 | 0.995 / 0.985 |

- The two models produce essentially the same masks on this material (IoU 0.995), so the lite model is the default: half the time, a quarter of the disk, MIT licence both.
- **Mask quality:** on a synthetic product fixture with an exact ground truth the lite model reaches **IoU 0.979** (`tests/gpu/test_background_gpu.py`, threshold 0.85). Visually (contact grids `grids/`, and the composite grids below) all ten subjects cut out cleanly, including curly hair and chair spindles. A chroma-key ground truth from generated green-screen images was tried and rejected as a metric: the generator renders green *rooms* (walls, floors, shadows), so the key measures the render, not the mask.
- VRAM: **0 MiB** — the model runs on the CPU, so segmentation and the engine are never resident together (R5).
- Rejected candidates (measured on 5 probe images, 2026-11-03 06:50-07:10 CST): `briaai/RMBG-1.4` ONNX (1.1-1.7 s but non-commercial per its README/licence, and it selected nearly a whole scene on one probe); `studioludens/birefnet-lite-512` (2.5 s, empty mask on an interior scene); `briaai/RMBG-2.0` (CC-BY-NC-4.0 and gated; not pinnable, documented as an optional extra).

**Compositing (CPU, per 1024x1024 subject):** segmentation 7.2-7.6 s + composite 0.2-0.8 s (colour match at strength > 0 adds the LAB transfer). The stage's preview runs the same composite.

**Colour match tuning (10 pairs, `grids/*-colour.jpg`):** strength 0 keeps the subject untouched but leaves it lit for another scene; the first formula (full LAB mean/std transfer) was **rejected**: at 1.0 it dragged a red mug to the background's dominant hue (brown), at 0.5 it muted it. The shipped formula transfers lightness (L) in full and only **35 %** of the background's tint statistics (mean and spread) on the chroma channels (`CHROMA_SIGMA`), which keeps a saturated subject's identity while the light matches. **Pick: on by default, strength 1.0** (`colour_match_strength`).

**Harmonize (relight) tuning:** light 0.25 / strong 0.45 denoise over the seam band (crop-and-stitch); measured below.

**Action count (Playwright, `e2e/background.spec.ts`, FakeEngine):** open result -> Background -> choose photo -> Apply -> Download = **4 actions** (Appendix B allows 5).

## Picks (ADR-0018, ADR-0010)
- **Default photoreal and avatar model:** RealVisXL V5.0 Lightning, DPM++ SDE Karras, 5 steps, CFG 1.5, fp16-fix VAE. 13.7 s native, 18.3 s at 1920×1080, 18.7 s at 2560×1440.
- **Quality model:** Juggernaut XL v9, DPM++ 2M Karras, 30 steps, CFG 4.5, baked VAE. 38.6 s native, ~41 s per wallpaper.
- **Wallpaper chain:** `model` (4×NomosWebPhoto RealPLKSR) by default; Quality = a refinement pass, provisionally `latent` (Phase 14 confirms `latent` vs `both`).
- **VRAM mode:** dynamic by default; `--disable-dynamic-vram --lowvram` for the OOM retry.
- **Default set size:** 14.4 GB (budget 30 GB).

## For the owner's review (H5, H10)
- Contact sheet, 16 prompts × 6 configurations at the native bucket: `~/.cache/p11/bench/contact-sheet.html` (and `.png`).
- Avatar sheet, portrait bucket: `~/.cache/p11/bench/avatar-sheet.html` (and `.png`).
- Raw JSON for every run: `~/.cache/p11/bench/runs/`; engine logs `~/.cache/p11/bench/engine-*.log`; candidate and download records `~/.cache/p11/bench/candidates/`.
- Inpaint tuning (Phase 10): grids `~/.cache/p11/bench/inpaint/grids/*.jpg`, results `~/.cache/p11/bench/inpaint/results/`, `results.json`.
Outputs from rejected models stay in the sheets after their weights were deleted.
