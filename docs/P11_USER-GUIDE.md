# P11 User Guide (outline)

Outline only; written out as features land (finished in Phase 15).

1. Install (`./install.sh`) and first run (`p11 doctor`, `p11 open`)
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
