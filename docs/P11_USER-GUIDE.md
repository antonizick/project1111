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

## 2. Generate (written in Phase 08)
![Generate view](images/p11-generate.png)

1. Type what you want to see in **Prompt**.
2. Pick a **Style** (Photoreal, 3D animated avatar, Logo flat, Logo 3D). The style also picks a sensible size, for example square for logos.
3. Pick a **Size**: Wallpaper 1920 × 1080 or 2560 × 1440, Square, or Avatar (portrait). Wallpapers are drawn at the model's native size and upscaled.
4. Press **Generate** or <kbd>Ctrl</kbd>+<kbd>Enter</kbd>. **Number of images** makes up to 4 at once.

While it runs you see the stage (Generating, Refining), the step, the percentage and an estimate of the time left; <kbd>Esc</kbd> or **Cancel** stops it. The first job after a pause takes about 15 s longer because the engine starts. If the GPU runs out of memory P11 says so and retries in low-memory mode.

**What you can do with a result:** **Variations** (<kbd>V</kbd>, same prompt, next seeds), **Tweak prompt** (one small wording change, same seed), **Upscale ×2**, **Favourite**, and **Download** (with **Strip metadata** on, the file carries no recipe, prompt or timestamps). **Save as Template** (<kbd>T</kbd>) is described under Templates. Inpaint, Background and Face show the phase that adds them.

**Advanced** (click "▸ Advanced"): model (with its family and a "default" badge), LoRAs and their weights, negative prompt, sampler, scheduler, steps, CFG, seed with **Lock seed**, and the upscale method. Empty fields use the model's tested defaults, shown as grey placeholders; **Reset to model defaults** clears your changes. With the seed locked, a batch uses seed, seed + 1, …

The status bar shows the engine state, the queue, GPU memory in use and the GPU temperature (green below 70 °C, yellow from 70, orange from 80, red from 87 °C when long jobs pause), and the model of your last job.

## 3. Gallery (written in Phase 08)
![Gallery](images/p11-gallery.png)

Every image is listed newest first, grouped by day. **Search prompts** matches word beginnings ("mount" finds "mountain"); filter by template, model or ★ favourites. Click an image to open it: zoom with the mouse wheel or <kbd>+</kbd>/<kbd>−</kbd> (<kbd>0</kbd> resets, drag or arrow keys to pan), go to the previous/next image, make variations, download, or **Open as recipe**, which loads its settings into Generate with the seed locked, so Generate makes the same picture again.

Tick the box on two or more images to **Compare** them side by side (zoom and pan move together), **Export** them as one ZIP (with or without metadata) or **Delete** them. Deleting moves the files to P11's trash folder (`~/.local/share/p11/trash/`); nothing is gone until you press **Empty trash** and confirm. To bring an image back before that, move its `.png` and `.json` back under `~/Pictures/P11/` and run a reindex (Phase 16 adds a button).

![Compare](images/p11-compare.png)

**Keyboard shortcuts** (press <kbd>?</kbd> in the app): <kbd>Ctrl</kbd>+<kbd>Enter</kbd> generate · <kbd>Esc</kbd> cancel the job or close a dialog · <kbd>V</kbd> variations · <kbd>T</kbd> save as template · <kbd>Ctrl</kbd>+<kbd>K</kbd> find and run a template · <kbd>G</kbd> gallery · <kbd>?</kbd> shortcuts. Letter keys do nothing while you are typing in a field. The theme button in the top bar switches light and dark.

## 4. Templates (written in Phase 09)
A template is a saved recipe you can run again with one click.

**Save one:** make an image you like, press **Save as Template** (<kbd>T</kbd>) under the result or in the gallery detail view, check the name (it starts from your prompt) and press **Save**. That is two actions. Optional: a folder (up to three levels, like `Logos/Dark`), tags, **A new seed** (more like this, the default) or **This seed** (exactly this), and **Ask for the prompt each time**, which turns the prompt into an input. If the image was made from a photo (a face, a background), that photo becomes an input to fill in; the photo itself is never stored in the template. A chain (for example generate, then upscale) is saved whole.

**Run one:** open **Templates**, press **Run** on a card. Press **Inputs…** to change the template's inputs first. A template whose required input is empty (a face photo, say) opens a small form: choose a photo or drop one on the field, tick *Remember* to reuse it next time, then **Run**. The result appears on the card, in Generate if you are there, and in the gallery under the template's name. In Generate, <kbd>Ctrl</kbd>+<kbd>K</kbd> opens a finder (type a few letters, <kbd>Enter</kbd> runs), and the last five templates you ran are buttons above the prompt.

**Manage:** search by name, tag or prompt; filter by folder and tag. **Edit** opens the recipe in Generate (the template itself is unchanged: save the result as a new template), **Duplicate**, **Rename**, **Move**, **Export** (a `.p11template.json` file) and **Delete** (a toast offers **Undo**). **Import…** reads a template file; P11 checks it and refuses files that are damaged or from a newer P11. Imported templates get a new ID, so they never overwrite yours.

**Starter templates** are added to your templates folder (`~/.config/p11/templates/starter/`) the first time P11 Studio starts: *Wallpaper photoreal 16:9 1080p* and *1440p*, *Software logo dark*, *Software logo light*, *Indie game logo* and *3D animated avatar (bobblehead)*. Each runs in one click and has a text input you can change. Until the text overlay arrives (Phase 14) the logo templates make the mark without text; the avatar's face photo input is optional and is used once face swap arrives (Phase 12). If you delete a starter it does not come back. To undo everything: delete the folder `~/.config/p11/templates/` (including `.starter-installed.json`, which makes the starters install again).

## 5. Inpainting and the mask editor (written in Phase 10)
Inpainting repaints the part of an image you paint over and leaves the rest untouched.

**Fix a result in four actions:** press **Inpaint** under a result (or in the gallery detail view), paint over the part to change with one stroke, press **Apply**, then **Download** (or **Save as Template**). The prompt starts as the image's own prompt; change it to say what should be there ("a red wool scarf"). To start from your own photo, open **Inpaint** in the left nav and choose **Upload photo** (PNG, JPEG or WebP; location data is removed on upload).

**Strength** (pick one):
- **Subtle fix** keeps the shapes and fixes details: skin, small artefacts, a smoother patch.
- **Change** (the default) changes what is there but keeps the layout: an expression, a colour, a material.
- **Replace** paints something new in the area: a different object, a new sky.

**Only masked area at full resolution** (on by default) paints a box around your mask at the model's working size and pastes it back, so small fixes keep their detail and run faster (about 11–15 s for a face on a 1920×1080 image instead of about 30 s for the whole frame). Turn it off to repaint with the whole image in view.

**Mask editor:** **Brush** (<kbd>B</kbd>) and **Eraser** (<kbd>E</kbd>), **Size** (<kbd>[</kbd> smaller, <kbd>]</kbd> bigger), **Hardness** (soft or hard edge), **Opacity** (a lighter mask changes the area less), **Feather** (how softly the new part blends in; the preview shows it), **Invert** (<kbd>I</kbd>: paint the part to keep instead), **Clear**, **Undo** (<kbd>Ctrl</kbd>+<kbd>Z</kbd>), **Redo** (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd>) and **Show mask** (<kbd>H</kbd>). Zoom with the mouse wheel or a touchpad pinch, pan by holding <kbd>Space</kbd> and dragging (or with the middle mouse button). A pen's pressure makes the brush thinner when you press lightly. <kbd>Ctrl</kbd>+<kbd>Enter</kbd> applies.

**Advanced:** an exact **Denoise** (overrides the strength buttons), **Mask blur**, **Padding** around the mask (more context for the model), **Steps** and a fixed **Seed**.

**After applying:** the result is saved as a child of the original in the gallery. **Keep editing this result** loads it into the editor for another fix. **Save as Template** asks whether to **Keep this mask in the template** (the mask shape is stored in the template; the run asks only for the image) or **Ask for a mask each time** (the run asks for a mask image, white = repaint). The photo itself is never stored in a template.

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
