# P11 User Guide (outline)

Outline only; written out as features land (finished in Phase 15).

1. Install (`./install.sh`) and first run (`p11 doctor`, `p11 open`); running the Studio (below)
2. Generate: Simple and Advanced modes, wallpaper presets, seeds and variations
3. Gallery: compare, export, re-run
4. Templates: save, apply, slots, import/export
5. Inpainting and the mask editor
6. Background replacement
7. Face-swap, pose and reference control (consent, NSFW target guard)
8. Video face-swap
9. Models: curated set, licence flags, adding your own
10. Troubleshooting: out-of-memory, thermals, `p11 doctor`
11. Uninstall and data locations

## 1. Running P11 Studio (written in Phase 07)
P11 Studio is a small local web service plus the engine it drives. Everything stays on `127.0.0.1`.

```bash
p11 start          # start the Studio in the background (the engine starts with the first job)
p11 open           # open it in an app window (starts the Studio first if needed)
p11 status         # Studio, engine, GPU temperature/VRAM and queue; exit 3 when not running
p11 stop           # stop the Studio and the engine
p11 serve          # run in the foreground instead (Ctrl+C to stop); --port, --debug
p11 doctor         # check GPU, engine, models, ports, disk space and permissions
p11 doctor --quick # skip the PyTorch/CUDA check (a few seconds)
```

`p11 open` uses the same app-mode window as Omarchy web apps (`omarchy-launch-webapp`), otherwise a Chromium-family browser with `--app`, otherwise your default browser. Set `P11_BROWSER="firefox --new-window"` to choose one. The link it opens contains a one-time code that works once, for two minutes; to get another window, run `p11 open` again. `p11 open --print-url` prints the link instead of opening it.

**The engine and the GPU.** The engine is started for the first job and stopped after 5 minutes without work (`engine_idle_stop = 300` in `~/.config/p11/config.toml`), so P11 does not hold on to the GPU while idle. After an "out of GPU memory" retry P11 runs in low-memory mode for that job and switches back to the faster mode after a minute of idle time. Long jobs pause while the GPU is above 87 °C and continue at 80 °C.

**Try it without a GPU.** `p11 serve --fake` (or `p11 start --fake`) uses a stand-in engine that draws placeholder images, with a demo gallery in `~/.cache/p11/fake/`, separate from your real pictures.

**Scripts.** The API is at `http://127.0.0.1:8111/api/` and needs the session token: `curl -H "Authorization: Bearer $(cat "$(p11 status --token-file)")" http://127.0.0.1:8111/api/system`. The schema is at `/api/openapi.json`.

**Logs.** `~/.cache/p11/logs/studio.log` (the Studio; never contains prompt text unless you run with `--debug`) and `engine.log` (ComfyUI).

**`p11 doctor` problems and what to do.**

| Message | Do this |
|---|---|
| No NVIDIA driver found / nvidia-smi cannot talk to the GPU | Check `nvidia-smi`; reboot after a driver update. P11 never installs drivers. |
| The engine is not installed / is ComfyUI x, P11 is pinned to v0.43.0 | `scripts/engine_setup.sh` (later: `./install.sh`) |
| The engine's PyTorch cannot use the GPU / has no kernels for sm_75 | `scripts/engine_setup.sh` reinstalls the pinned CUDA build |
| Default model … is not installed (for example after renaming a file) | `p11 models install default` (only missing files are downloaded) |
| Port 8111 / 8188 is used by another program | stop it, or set `studio_port` / `engine_port` in `config.toml` |
| Some P11 data is readable by other users | run the `chmod` command it prints |

## 9. Models (written in Phase 06)
P11 ships a list of tested models (`models/manifest.toml`), not the models themselves. Each one is downloaded from its original host and checked against a pinned SHA-256 before P11 uses it.

```bash
p11 models list                       # what P11 knows and what is installed
p11 models licences                   # licence, "commercial use" flag, your acknowledgements
p11 models install default --dry-run  # size before downloading (default set: 14.4 GB)
p11 models install default            # asks you to accept licences with terms (or --accept-licences)
p11 models install full               # adds the SD 1.5 low-VRAM model
p11 models verify                     # re-hash every installed file; exit 1 if one is damaged
```
An interrupted download resumes when you run the same command again. A file that does not match its hash is deleted and reported, never used. Licence acknowledgements are kept in `~/.config/p11/licences.toml` with the time you accepted them; delete an entry to be asked again.

**Licences.** Several models use OpenRAIL-family licences: commercial use is allowed, but the licence lists uses you agree not to make. CC-BY models need credit when you share results. `p11 models licences` shows the flags for each.

**Adding your own models.**
```bash
p11 models add ~/Downloads/MyLora.safetensors          # copied into the right folder
p11 models add ~/Models/big.safetensors --link         # symlink instead of copying
p11 models add https://huggingface.co/<repo>/resolve/<commit>/<file>.safetensors
p11 models add file.safetensors --kind upscale --id my-upscaler   # when detection cannot tell
p11 models disable my-upscaler / enable my-upscaler
p11 models remove my-upscaler                          # forget it; --delete-file also deletes it
```
P11 recognises the file type by its content, not its name. `.safetensors` and GGUF files are accepted. Pickle-based files (`.ckpt`, `.pt`, `.pth`, `.bin`) can run code on your computer when loaded, so P11 refuses them unless you pass `--allow-pickle`; prefer a `.safetensors` version. If the file you add is one of the curated models, P11 installs it as that model. Files you drop into a model folder by hand show up as `unregistered` until you `add` them.

**Optional models that need a login.** The curated set needs no account. For a model behind a login, put a token in `~/.config/p11/secrets.toml` (mode `600`, or P11 refuses it):
```toml
[tokens]
"huggingface.co" = "hf_…"
```
The token is only sent to that exact host, never to the CDN the host redirects to, and never logged.

**Moving models to another disk:** set `models_root = "/path"` in `~/.config/p11/config.toml`, move the folders, then run `p11 models install default` once (it checks the files and updates the engine's `extra_model_paths.yaml`).
