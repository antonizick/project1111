"""A stand-in for ComfyUI's HTTP + websocket API, for testing ``ComfyEngine`` without a GPU.

``ComfyEngine`` launches it exactly like the real engine (``python main.py --listen … --port …``).
It speaks the endpoint and message shapes of ComfyUI v0.43.0 (see ``p11.engine.comfy``) and runs
the graphs on a ``FakeEngine``, so validation, progress, outputs, OOM and interrupts behave as in
the contract suite. ``--lowvram`` on the command line switches the fake to low-VRAM mode.
Test-only control: ``POST /mock/fail {"kind": …}`` and ``GET /mock/state``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import email.parser
import email.policy
import json
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from p11.engine.base import (
    EngineEvent,
    EngineExecutionError,
    EngineInterrupted,
    EngineOOM,
    EngineValidation,
    Executed,
    Executing,
    Progress,
)
from p11.engine.fake import FakeConfig, FakeEngine

parser = argparse.ArgumentParser()
parser.add_argument("--listen", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8188)
parser.add_argument("--lowvram", action="store_true")
args, _unknown = parser.parse_known_args()

fake = FakeEngine(
    FakeConfig(step_delay=0.05, node_delay=0.0), vram_mode="lowvram" if args.lowvram else "dynamic"
)
sockets: dict[str, WebSocket] = {}
history: dict[str, dict[str, Any]] = {}
outputs: dict[tuple[str, str], bytes] = {}
freed: list[dict[str, Any]] = []
running: dict[str, Any] = {"prompt_id": None}


async def send(sid: str, typ: str, data: dict[str, Any]) -> None:
    ws = sockets.get(sid)
    if ws is not None:
        await ws.send_text(json.dumps({"type": typ, "data": data}))


async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    sid = ws.query_params.get("clientId") or uuid.uuid4().hex
    sockets[sid] = ws
    await send(sid, "status", {"status": {"exec_info": {"queue_remaining": 0}}, "sid": sid})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        sockets.pop(sid, None)


async def system_stats(_: Request) -> Response:
    gib = 1024**3
    return JSONResponse(
        {
            "system": {
                "os": "linux",
                "ram_total": 32 * gib,
                "ram_free": 24 * gib,
                "comfyui_version": "0.43.0",
                "python_version": sys.version,
                "pytorch_version": "mock",
                "argv": ["main.py", *sys.argv[1:]],
            },
            "devices": [
                {
                    "name": "cuda:0 Mock GPU",
                    "type": "cuda",
                    "index": 0,
                    "vram_total": 8 * gib,
                    "vram_free": 7 * gib,
                    "torch_vram_total": 0,
                    "torch_vram_free": 0,
                }
            ],
        }
    )


async def post_prompt(request: Request) -> Response:
    body = await request.json()
    nodes = body["prompt"]
    prompt_id = body.get("prompt_id") or str(uuid.uuid4())
    sid = body.get("client_id", "")
    try:
        fake._validate(nodes)
    except EngineValidation as exc:
        node = exc.node or ""
        cls = nodes.get(node, {}).get("class_type", "") if node else ""
        return JSONResponse(
            {
                "error": {
                    "type": "prompt_outputs_failed_validation",
                    "message": "Prompt outputs failed validation",
                    "details": "",
                    "extra_info": {},
                },
                "node_errors": {
                    node: {
                        "errors": [
                            {"type": "value_not_in_list", "message": exc.detail, "details": ""}
                        ],
                        "dependent_outputs": [],
                        "class_type": cls,
                    }
                }
                if node
                else {},
            },
            status_code=400,
        )
    asyncio.get_running_loop().create_task(execute(prompt_id, sid, nodes))
    return JSONResponse({"prompt_id": prompt_id, "number": 0, "node_errors": {}})


async def execute(prompt_id: str, sid: str, nodes: dict[str, Any]) -> None:
    running["prompt_id"] = prompt_id
    base = {"prompt_id": prompt_id}

    async def on_event(ev: EngineEvent) -> None:
        if isinstance(ev, Executing):
            await send(sid, "executing", {"node": ev.node, "display_node": ev.node, **base})
        elif isinstance(ev, Progress):
            await send(
                sid, "progress", {"value": ev.step, "max": ev.total, "node": ev.node, **base}
            )
        elif isinstance(ev, Executed):
            await send(sid, "executed", {"node": ev.node, "output": dict(ev.outputs), **base})

    await send(sid, "execution_start", base)
    try:
        result = await fake.run(nodes, on_event=on_event)
    except EngineInterrupted:
        await send(sid, "execution_interrupted", {"node_id": "0", "node_type": "", **base})
    except EngineOOM as exc:
        await send(sid, "execution_error", error(base, "torch.OutOfMemoryError", str(exc)))
    except EngineExecutionError as exc:
        await send(sid, "execution_error", error(base, exc.exception_type, exc.detail))
    else:
        out: dict[str, Any] = {}
        for img in result.images:
            outputs[("p11", img.filename)] = img.data
            entry = {"filename": img.filename, "subfolder": "p11", "type": "output"}
            out.setdefault(img.node, {"images": []})["images"].append(entry)
        history[prompt_id] = {"outputs": out, "status": {"status_str": "success"}}
        await send(sid, "execution_success", base)
        await send(sid, "executing", {"node": None, **base})
    finally:
        running["prompt_id"] = None


def error(base: dict[str, Any], etype: str, message: str) -> dict[str, Any]:
    return {
        **base,
        "node_id": "6",
        "node_type": "KSampler",
        "executed": [],
        "exception_message": message,
        "exception_type": etype,
        "traceback": [],
        "current_inputs": {},
        "current_outputs": [],
    }


async def get_history(request: Request) -> Response:
    pid = request.path_params["prompt_id"]
    return JSONResponse({pid: history[pid]} if pid in history else {})


async def post_history(request: Request) -> Response:
    body = await request.json()
    for pid in body.get("delete", []):
        history.pop(pid, None)
    return Response(status_code=200)


async def view(request: Request) -> Response:
    key = (request.query_params.get("subfolder", ""), request.query_params["filename"])
    data = outputs.pop(key, None)
    if data is None:
        return Response(status_code=404)
    return Response(data, media_type="image/png")


async def upload_image(request: Request) -> Response:
    raw = await request.body()
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + raw)
    fields: dict[str, Any] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        fields[str(name)] = (part.get_filename(), part.get_payload(decode=True))
    filename, data = fields["image"]
    fake.uploads[filename] = data
    return JSONResponse({"name": filename, "subfolder": "", "type": "input"})


async def interrupt(_: Request) -> Response:
    await fake.interrupt()
    return Response(status_code=200)


async def free(request: Request) -> Response:
    freed.append(await request.json())
    return Response(status_code=200)


async def mock_fail(request: Request) -> Response:
    body = await request.json()
    fake.fail_next(body["kind"], body.get("node"))
    return Response(status_code=200)


async def mock_state(_: Request) -> Response:
    return JSONResponse(
        {"freed": freed, "vram_mode": fake.vram_mode, "uploads": sorted(fake.uploads)}
    )


@contextlib.asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    await fake.start()
    yield


app = Starlette(
    routes=[
        WebSocketRoute("/ws", ws_endpoint),
        Route("/system_stats", system_stats),
        Route("/prompt", post_prompt, methods=["POST"]),
        Route("/history/{prompt_id}", get_history),
        Route("/history", post_history, methods=["POST"]),
        Route("/view", view),
        Route("/upload/image", upload_image, methods=["POST"]),
        Route("/interrupt", interrupt, methods=["POST"]),
        Route("/free", free, methods=["POST"]),
        Route("/mock/fail", mock_fail, methods=["POST"]),
        Route("/mock/state", mock_state),
    ],
    lifespan=lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host=args.listen, port=args.port, log_level="warning")
