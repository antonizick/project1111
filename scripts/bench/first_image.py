"""Time to first image on a fresh install (spec R4): Studio start + engine start + one wallpaper.

Run it with the environment of the install under test (HOME, XDG_*), after the models are in place:
    HOME=/tmp/p11-home .../p11-python scripts/bench/first_image.py [--aspect 16:9-1080p]
Prints one JSON line. Uses the installed `p11` command and the Studio API; stops the Studio at the end.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime

import httpx

from p11.recipe.model import FixedSeed, Generate, Recipe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aspect", default="16:9-1920x1080")
    ap.add_argument("--p11", default="p11")
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args()
    t0 = time.monotonic()
    subprocess.run([args.p11, "start"], check=True, capture_output=True)
    try:
        status = json.loads(
            subprocess.run(
                [args.p11, "status", "--json"], check=True, capture_output=True, text=True
            ).stdout
        )
        token_file = subprocess.run(
            [args.p11, "status", "--token-file"], check=True, capture_output=True, text=True
        ).stdout.strip()
        token = open(token_file).read().strip()
        t_studio = time.monotonic() - t0
        recipe = Recipe(
            id="r-first-image",
            name="First image",
            created_at=datetime.now(UTC).isoformat(),
            seed=FixedSeed(value=1111),
            steps=(
                Generate(
                    prompt="a lighthouse on a rocky coast at sunrise, photo", aspect=args.aspect
                ),
            ),
        ).model_dump(mode="json")
        with httpx.Client(
            base_url=status["url"], headers={"authorization": f"Bearer {token}"}, timeout=30
        ) as c:
            job = c.post("/api/jobs", json={"recipe": recipe}).json()
            while True:
                j = c.get(f"/api/jobs/{job['id']}").json()
                if j["state"] in ("done", "failed", "cancelled"):
                    break
                if time.monotonic() - t0 > args.timeout:
                    j = {"state": "timeout"}
                    break
                time.sleep(0.5)
        total = time.monotonic() - t0
        out = {
            "state": j["state"],
            "studio_ready_s": round(t_studio, 1),
            "first_image_s": round(total, 1),
            "aspect": args.aspect,
        }
        print(json.dumps(out))
        return 0 if j["state"] == "done" else 1
    finally:
        subprocess.run([args.p11, "stop"], check=False, capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
