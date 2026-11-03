"""Hold all but ``argv[1]`` MiB of free VRAM until stdin closes (run with the engine's Python).

The gpu OOM tests use it to put the real engine under memory pressure, because ComfyUI slows
down instead of failing on an oversized latent.
"""

import sys

import torch

leave_mib = int(sys.argv[1])
free, _total = torch.cuda.mem_get_info()
block = torch.empty(max(0, free - leave_mib * 1024 * 1024), dtype=torch.uint8, device="cuda")
print(
    f"hog {block.numel() // 2**20} MiB, free {torch.cuda.mem_get_info()[0] // 2**20} MiB",
    flush=True,
)
sys.stdin.read()
