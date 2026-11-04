# P11 Benchmarks

**Last updated:** 2026-11-03 20:22 CST (Phase 16). Measured on the reference laptop by `scripts/bench/` against the pinned engine. Later phases append their own sections (Phase 05: adapter overhead; Phase 16: success criteria).

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

**Edge (halo) tuning, 100 % crops (`~/.cache/p11/phase11/seam-*.jpg`):** three findings, all fixed before the picks.
- Unmixing the edge against the **new** background (first version) left a white rim on the mug; the spill to remove is the **old** background, now estimated locally from confident background pixels just outside the matte (`spill_background`, normalized blur).
- A plain Gaussian feather spreads alpha **outside** the matte, so a translucent band of the old scene showed around the mug. The feather now works inward: binarize at 50 %, erode by `feather/2`, blur by `feather/4`, capped by the matte itself (alpha ≈ 2 % at the matte's edge). Eroding by the full feather ate the mug's handle; half keeps it.
- **Result at the defaults (feather 8 px, colour match 1.0):** the mug's body and handle and the portrait's hair edge show no halo at 100 %. Remaining: a few specks of the old wall where the matte keeps soft hair wisps, and thin chair spindles lose some opacity (follow-up; Edge feather 0 keeps them).

**Memory:** ONNX Runtime's CPU arena kept ~12 GB resident after a 1024² BiRefNet-lite run (measured max RSS 11.8 GB); with `enable_cpu_mem_arena = False` the peak is 6.6 GB during a run and is released after it, at the same speed (7.2–7.7 s warm). The Studio uses the arena-free setting.

**Harmonize (relight) tuning** (10 pairs x Light 0.25 / Strong 0.45, through the Studio API on the pinned engine, power profile `performance` then restored to `power-saver`, AC; seed 77):

| Harmonize | Wall s (median) | Engine s (median) | Peak VRAM | Peak GPU temp |
|---|---|---|---|---|
| Light 0.25 | 20.2 | 18.9 | 7.7 GB | 68 °C |
| Strong 0.45 | 16.3 | 14.8 | 7.7 GB | 68 °C |

- 20/20 runs finished, **no OOM** (peak whole-card VRAM 7,736 MiB with the desktop, dynamic VRAM); the first run includes the cold model load (36.6 s wall). Times include the CPU segmentation (~8–10 s) inside the job; the engine pass over the seam crop is ~6–10 s. Light runs measured slower than Strong only because each subject's first job paid the segmentation and upload; the pass itself has the same steps.
- **Picks:** Harmonize **Light 0.25** by default (unifies the light along the seam without repainting the subject), **Strong 0.45** as the option, Off = local composite only (~8–11 s total, no engine). Colour match **on, strength 1.0**; Edge feather **8 px**.
- **Acceptance budget:** one Apply on the defaults (auto-mask + colour match + Light harmonize) on a 1024² subject ≈ **20 s** warm (≤ 37 s from a cold engine); recorded by `tests/gpu/test_background_gpu.py`.

**Action count (Playwright, `e2e/background.spec.ts`, FakeEngine):** open result -> Background -> choose photo -> Apply -> Download = **4 actions** (Appendix B allows 5).

## Face, pose and reference (Phase 12, ADR-0028…0031)

Measured on the reference laptop (i7-9750H CPU for the face pipeline and the map makers, RTX 2070
Mobile for the generations) by `tests/gpu/test_face_pose_gpu.py`, whose numbers land in
`~/.cache/p11/face-pose/measurements.json`. Everything is synthetic (S6): the faces are P11-generated
portraits, the poses are skeletons drawn in code, the reference is a generated picture.

**Faces (CPU, no VRAM, ADR-0028).** 1024×1024 P11-generated portraits:

| Step | Time | Notes |
|---|---|---|
| YuNet detection (two sizes merged) | 0.03–0.44 s | first call slower (model load) |
| ArcFace embedding | ~0.2 s | 512-d |
| `inswapper_128` swap + paste-back | **2.4 s** | 128-px aligned face, feathered box mask |
| swap + GFPGAN v1.4 restore | **3.9 s** | 512-px FFHQ alignment, full-strength blend |
| whole `face_swap` job (submit → saved) | 11.2 s first, ~4 s after | includes the guard, uploads and indexing |

Identity transfer is convincing at 100 % and GFPGAN cleans up the 128-px swap without over-smoothing
(crops kept in `~/.cache/p11/face-pose/` and `~/.cache/p11/phase12/proto/`). This is what decided
ADR-0028 over a ComfyUI node or the FaceFusion CLI: same algorithm, no engine involvement, no VRAM,
2.4 s per frame — which is the number Phase 13's video path multiplies.

**The S5 guard (ADR-0029).** 1.8 s cold, **0.7 s** warm for both classifiers together (Marqo
ViT-tiny 384 + Freepik EVA02 448, CPU). On the synthetic portraits it says safe, as it must
(P(NSFW) 0.069 and 0.058 on one portrait). It runs twice per swap (target and result) and once more
at submit time, so a swap costs about 2 s of checking; the refusal path is covered by the stub tests.

**Pose (ADR-0030).** DWPose extraction from a photo: **0.3–0.9 s** per picture (YOLOX-L + RTMPose-l
on the CPU), giving 18 body keypoints; a full-body generated figure yields 12–18 visible joints. The
OpenPose picture is drawn in ~10 ms. The acceptance measure is a **pose distance**: DWPose reads the
result back and the mean distance between matching joints is compared with the skeleton that was
applied **0.061** of the picture (asserted < 0.2; recorded in
`~/.cache/p11/face-pose/measurements.json` alongside these tables). A 1024×1024 generation with the union ControlNet follows the
skeleton and ran **61 s end to end on its first run** (cold engine + loading the 2.5 GB
ControlNet-Union ProMax) — the steady-state figure is the ordinary ~14 s of a Lightning 1024²
generation once the model is resident. No OOM at the default preset; the ControlNet adds about
2.5 GB of VRAM while it runs.

**Reference (ADR-0031).** A style reference (a generated watercolour) applied to four seeds of
"a lighthouse on a cliff at dusk" at 1024x1024, weight 0.75:

| Run | Wall time | Notes |
|---|---|---|
| first with a reference | 24.8 s | cold: loads CLIP ViT-H/14 (2.5 GB) + IP-Adapter Plus |
| runs 2-4 | **12.7 s** | warm, i.e. the same as a plain Lightning 1024x1024 generation |

The four results keep one look (same dusk palette, same painterly treatment) while the composition
changes with the seed - the picture is `~/.cache/p11/face-pose/reference-seed-5{1..4}.png`, alongside
the swap and pose results and a contact sheet (`sheet.jpg`). The face variant (`character` mode) uses
the same path with `ip-adapter-plus-face-sdxl`. Cost on the GPU: the CLIP encoder and the adapter are
resident only while the step runs; no OOM at the default preset.

**VRAM and disk.** Nothing in the face path touches the GPU (it runs with the engine stopped). The
`face` set is 1.43 GB and the `control` set is 7.23 GB (2.5 GB of which is the CLIP ViT-H encoder and
2.5 GB the union ControlNet); the default set is unchanged at 14.63 GB.

## Video face-swap (Phase 13, ADR-0033, ADR-0034)

Measured on the reference laptop (the face pipeline is CPU work on the i7-9750H; the GPU is only
watched for the thermal curve) by `tests/gpu/test_video_gpu.py` and `scripts/bench/video_bench.py`,
whose numbers land in `~/.cache/p11/video/measurements.json` and
`~/.cache/p11/bench/video/measurements.json`. Everything is synthetic (S6, H7): the clips are slow
zooms over a P11-generated portrait with a generated sine tone, so every frame carries a face.

**Pipeline cost (320x320, 3 s at 10 fps, Fast; `tests/gpu/test_video_gpu.py`).** 30 frames end to
end (extract + guard pre-pass + 30 swaps + stitch) in **105.9 s** — **3.53 s per frame** wall time
at that size. The swap itself is the Phase 12 number (2.4 s, 3.9 s with GFPGAN) plus the S5 guard,
which runs twice per frame (target and result, ADR-0034; ~0.7 s per verdict warm, Phase 12): the
guard is the price of checking every frame, recorded on purpose.

**30 s 1920x1080 30 fps clip (900 frames), Fast and Good** (`scripts/bench/video_bench.py material
fast good`; power profile `performance` during the runs, restored to `power-saver` after, H8; AC):

| Quality | Frames | Swap stage | Per frame | Whole job | Peak GPU | Thermal pauses | Output |
|---|---|---|---|---|---|---|---|
| Fast (no restore, 720p frames) | 900 | 2340 s | **2.75 s** | ~40 min | 58 °C | 0 | 1280x720, 30.0 s, AAC copied |
| Good (GFPGAN, full size) | 484 of 900 | 3342 s for 484 | **6.9 s** | ~1 h 45 min projected | 53 °C (mid-run sample) | 0 | not stitched (run cut, see below) |

The Good row is a **partial** run: the harness's one-hour wait ran out at frame 484 (now four
hours, `video_bench.py`), so the clip was not stitched; the per-frame time is measured over those
484 full-size frames with GFPGAN (15:23–16:19 CST), and the whole-job figure is projected from it.
The output path itself (stitch, audio, player) is the same as Fast's and was proven there. The
scratch frames were deleted.

The Fast row is the **killed-and-resumed** run: the Studio died at frame 45 (the agent session
that hosted it ended), the next Studio start marked the job interrupted, and a Resume continued in
the same scratch at frame 46 and finished all 900 frames (855 swapped in 2350 s; extract 40.9 s,
stitch 7.7 s). The finished file is 30.0 s with the original AAC track and plays in the Studio's
`<video>` player; the scratch frames were deleted afterwards. A first attempt on a busy machine
measured 5–7 s per frame — the per-frame time is CPU-bound and halves when nothing else runs. One
1080p frame through `run_face_swap` alone (both guard verdicts, detection, swap, PNG encode) took
3.0 s, and 4.5 s with GFPGAN, measured once on an otherwise idle machine.

**Thermal guard (R14, H9).** The video job is CPU work, so the GPU sits idle near its desktop
temperature (peak **58 °C** over the 30 s Fast run, never near the 87 °C pause): owner question 5's
87/80 °C stands and no ±5 °C tuning was warranted (H9). The pause and resume themselves were proven
with the thresholds lowered to 50/45 °C: the job paused on its first frame batch with a
"Paused: the GPU is at 53 °C" note and resumed when the readings fell below 45 °C
(`tests/gpu/test_video_gpu.py::test_thermal_pauses_and_resumes_the_video_job`; readings offset from
the live NVML sensor so the test is deterministic).

**Kill, resume and cancel on the real service** (`scripts/bench/video_bench.py resume`, a 4 s
640x480 clip, `p11 serve` as its own process group): `SIGKILL` of the service at frame 3 → restart →
the job is `failed` with `job.interrupted` and listed as resumable → Resume finished all 40 frames
(163.9 s total including the restart); a second job cancelled at frame 2 left **no** scratch frames
behind (`~/.cache/p11/jobs/<job>/frames` deleted). Plus the 30 s 1080p kill-and-resume above.

**Temporal smoothing (task 5)** (`scripts/bench/video_bench.py smooth`, the same 4 s 640x480
clip at Fast, 2026-11-03 16:53 CST). Flicker proxy: mean absolute difference between consecutive
frames (grey, 0–255). The source clip (a slow zoom) is **1.955**; swapped without smoothing
**1.985** (the swap adds only +0.03, because the face is picked consistently by box overlap);
swapped with smoothing **1.761**, below the source, because the blend with the previous output
also damps the zoom's own motion inside the face box. So on this material the plain swap barely
flickers and smoothing is a mild trade (steadier face, slightly laggy on motion); it stays **off by
default** and optional, as the prompt asked. The smoothing run cost no extra time (78.6 s warm vs
199.4 s for the first run, which loaded the face models).

## Upscale Speed and Quality (Phase 14, ADR-0010, ADR-0035)
Measured 2026-11-03 17:25 CST by `tests/gpu/test_quality_upscale_gpu.py` on the reference laptop (RTX 2070 Max-Q, performance profile on AC, restored afterwards; RealVisXL V5.0 Lightning, seed 2222, one warm-up run per case, engine in default dynamic-VRAM mode). Raw times in `~/.cache/p11/bench/quality/times.jsonl` (not committed).

| Output | Speed (`model` chain) | Quality (`latent` chain) | OOM |
|---|---:|---:|---|
| 1920 x 1080 | 15.8 s | 34.9 s | none |
| 2560 x 1440 | 16.5 s | 76.6 s | none |

Quality at 2560x1440 is the slow case (tiled VAE decode of the refinement pass); it stays within the ~7 GB budget. Phase 03's `both` chain (55 / 88 s) was not re-run; `latent` remains the Quality chain on time and memory. Not measured in Phase 14: the by-eye `latent` versus `both` comparison, a 10-prompt defaults review and avatar-preset consistency across seeds (follow-ups).

## Time to first image after install (Phase 15, spec R4)
Measured 2026-11-03 18:29 CST on the reference laptop (RTX 2070 Max-Q, driver 615.78.08), plugged in, power profile `performance` (restored to `power-saver` afterwards, H8), GPU lock held. A throw-away `HOME` (`~/.cache/p11-throwaway`, deleted afterwards) with `P11_MODELS_FROM=~/.local/share/p11/models ./install.sh --yes --models default --accept-licences`, then `scripts/bench/first_image.py`: `p11 start`, one 1920x1080 photoreal wallpaper through the Studio API, cold (the engine starts with the job).

| Step | Result |
|---|---|
| `install.sh` total (system check, uv tool install, engine venv with torch 2.14.1+cu130, models reused by hard link, doctor, desktop entry) | 147 s (torch and Python wheels came from the local uv cache, so the network part of a first-ever install is not included) |
| Model download | not measured: reused (H1); the default set is 14.6 GB |
| Studio ready after `p11 start` | 2.9 s |
| **Time to first image** (start Studio, start engine, load the model, generate 1920x1080) | **43.1 s** (R4 target: 5 minutes after the download) |
| Second `install.sh` run | "Nothing to do", no step changed |
| `p11 doctor` after install | All good |

Clean install in a stock Arch container (`tests/install/run.sh`, `--gpus all`): install, doctor, a second run saying "Nothing to do", `p11 start --fake`/`status`/`stop`, desktop entry present, uninstall removes the engine: `CLEAN-INSTALL-OK` (2026-11-03 18:24 CST).

## Success criteria (Phase 16, spec §1, §10, R22, Appendix B)
Measured 2026-11-03 18:52–20:20 CST on the reference laptop, on AC power, power profile `performance` during every GPU stage and restored to `power-saver` after each (H8), GPU lock held (R24). The GPU stages ran through the **Studio API on the real engine** (`scripts/bench/qa.py`: the in-process Studio, `ComfyEngine`, default model RealVisXL V5.0 Lightning unless stated), so they include job queueing, saving, PNG metadata and gallery indexing. Times are submit to saved. Raw JSON: `~/.cache/p11/bench/qa/` (not committed).

| Criterion (source) | Target | Measured | Met? |
|---|---|---|---|
| Time to first image after the default-set download (§1, R4) | ≤ 5 min | **37.7 s** (throw-away HOME, `install.sh --models default` reusing the models by hard link, then `scripts/bench/first_image.py`: Studio ready 2.6 s, cold engine, 1920×1080). `install.sh` itself: 184 s (uv cache warm) | ✅ |
| Wallpaper presets without OOM, 50 in a row each (DoD) | 0 OOM | 1920×1080: **50/50**, 2560×1440: **50/50**, 0 failures, 0 OOM retries; peak VRAM 7690 MiB total | ✅ |
| Stable on 8 GB without VRAM tuning (§1) | no crash, no leak | 30-min mixed soak below: 105 jobs, 0 OOM, 0 crashes, RSS flat | ✅ |
| Daily workflow ≤ 5 actions (§1, App. B) | ≤ 5 | Generate (1) + background path 4 = **5**; generate → download **2**; inpaint path **4** | ✅ |
| Save as template ≤ 3, re-run 1 (§1, App. B) | ≤ 3 / 1 | **2** / **1**; a one-slot template run **3**; logo template with its text slot **3**; Models page install (licence accepted) **4** | ✅ |
| Inpaint, background, face, pose, reference work from Simple mode without docs (§1, §10) | end-to-end | Playwright walkthroughs on the FakeEngine (26 passed, 2 real-engine specs skipped, twice in a row) plus the mixed soak on the real engine; axe clean on every view | ✅ |
| Short video face-swap usable, resume after kill (§10, DoD) | usable MP4 with audio | Phase 13 measurements (below, "Video face-swap"): 30 s 1080p Fast 2.75 s/frame, killed and resumed to completion; Good ~6.9 s/frame (projected, the 4 h run was not repeated) | ✅ (Good row projected, H12) |
| No content filter on generation (A5); S5 guard on face paths | | `tests/unit/test_likeness_guard.py::test_a_style_reference_stays_unfiltered`; S5 coverage in `docs/P11_THREAT-MODEL.md` §5 | ✅ |

**Per-preset times** (`qa.py presets`: per combination one cold run, the engine starting with the job, then 3 warm runs):

| Preset | Mode | Cold | Warm median (min–max) |
|---|---|---:|---:|
| 1920×1080 | Speed (`model` chain) | 28.4 s | 16.2 s (16.0–16.2) |
| 1920×1080 | Quality (`latent` refine) | 46.2 s | 35.6 s (35.0–35.7) |
| 2560×1440 | Speed | 29.2 s | 17.8 s (17.8–17.9) |
| 2560×1440 | Quality | 70.7 s | 59.4 s (59.4–59.8) |

Quality at 2560×1440 came in under Phase 14's 76.6 s (a different harness, prompt and seed; the cause was not investigated); every run finished, peak VRAM 7708 MiB, max 76 °C.

**50-run soak per preset** (`qa.py soak`, 10 photoreal prompts in rotation, distinct seeds): 1920×1080 median 17.6 s (mean 17.8, 17.1–28.8; the 28.8 s is the cold first run); 2560×1440 median 17.9 s (mean 18.2, 17.8–29.4). The counterbalanced run order Phase 05 asked for: the two blocks differ by 0.3 s, within the cold-run noise, so the warm-GPU drift is negligible.

**Mixed 30-minute soak** (`qa.py mixed`, 19:41–20:13 CST): 15 cycles of generate 1920×1080 → inpaint (ellipse mask) → background (flat colour) → generate portrait → face swap (S5 guard on) → upscale to 2560×1440 → model switch to Juggernaut XL v9 and back.

| Job | n | Median | Max |
|---|---:|---:|---:|
| generate 1920×1080 (after a model switch) | 15 | 22.9 s | 29.1 s |
| inpaint | 15 | 17.1 s | 17.7 s |
| background | 15 | 11.7 s | 13.7 s |
| portrait 1024² | 15 | 12.2 s | 14.2 s |
| face swap + restore | 15 | 5.2 s | 8.2 s |
| upscale to 2560×1440 | 15 | 12.2 s | 12.6 s |
| Juggernaut XL v9 1920×1080 (switch) | 15 | 43.0 s | 50.2 s |

0 OOM, 0 crashes. 3 of 15 background jobs were refused with the plain-English "could not find a subject" (their bases were landscapes with no subject: correct behaviour, not a defect). **No leak:** Studio RSS 2.28 GB after the first face swap loaded the CPU models, then 2.28–2.30 GB every cycle to the end; engine RSS 9.35–9.64 GB, flat from cycle 4 on; GPU VRAM peak per 5-minute window 7689 → 7657 MiB, never growing. GPU max 79 °C.

**10-minute thermal loop** (`qa.py thermal`, 19:31–19:41 CST, directly after the soak, heat-soaked): 33 images at 1920×1080, median 17.9 s, the last five 18.1–18.3 s (no slowdown).

| Minute | Temp °C (avg / max) | SM clock MHz (avg / max) | Power W (avg / max) |
|---:|---|---|---|
| 0 | 77 / 78 | 1252 / 1770 | 61 / 80 |
| 2 | 79 / 79 | 1329 / 1770 | 69 / 78 |
| 4 | 79 / 80 | 1381 / 1770 | 66 / 81 |
| 6 | 80 / 81 | 1357 / 1755 | 67 / 74 |
| 8 | 80 / 80 | 1365 / 1755 | 68 / 78 |
| 10 | 80 / 81 | 1518 / 1755 | 65 / 74 |

No thermal slowdown bit was set in any sample; the plateau is 80–81 °C, under the 87 °C pause (H9).

**Network during the session (S1).** A watcher (`ss -tunp` once a second) recorded every socket of the bench Studio and, from 19:34, of the engine process with a non-loopback peer, from 19:00 to 20:15 CST (2280 samples with the engine included): **none**. Listeners: engine `127.0.0.1:8188` only; the Studio `127.0.0.1` only. The Playwright network guard (every spec) saw no request leave the Studio's origin.

**Security checks against a running Studio** (`p11 serve --fake` on 127.0.0.1:18311, curl, 2026-11-03 19:48 CST): `/healthz` 200; `/api/system` without a token 401, with it 200; `Host: evil.example` 421; a POST with `Origin: http://evil.example` 403; `Sec-Fetch-Site: cross-site` read 403; a POST carrying only the cookie 401; a non-ASCII token 401 (was a 500 before the Phase 16 fix); a websocket upgrade 403; `/` carries the full CSP, `nosniff`, `no-referrer` and `X-Frame-Options: DENY`.

**Clean install in a container** (`tests/install/run.sh`): stock Arch image, `--gpus all`, `install.sh --yes --models none`, `p11 doctor`, a second run says "Nothing to do", `p11 start --fake`/`status`/`stop`, desktop entry present, `uninstall.sh` removes the engine: **`CLEAN-INSTALL-OK`** in 233 s (2026-11-03 20:25 CST).

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
