"""Map P11's typed errors to plain-English problems with a hint (spec R5, shared instructions §3).

Used for failed jobs (stored on the job) and for API error responses (with an HTTP status).
"""

from __future__ import annotations

from pydantic import ValidationError

from p11.engine.base import (
    EngineCrashed,
    EngineError,
    EngineExecutionError,
    EngineInterrupted,
    EngineOOM,
    EngineTimeout,
    EngineUnavailable,
    EngineValidation,
)
from p11.gpulock import GpuLockTimeout
from p11.media.composite import CompositeError
from p11.media.control import ControlError
from p11.media.faces import FaceError
from p11.media.ffmpeg import VideoError as FfmpegError
from p11.media.imageio import ImageError
from p11.media.inpaint import MaskError
from p11.media.inputs import UnknownInput
from p11.media.nsfw import GuardRefused, GuardUnavailable
from p11.media.pose import PoseError
from p11.media.segment import SegmentationError
from p11.media.text import TextError
from p11.media.validate import UploadRejected
from p11.recipe.compile import CompileError, SlotBindingError
from p11.recipe.migrate import RecipeFormatError, RecipeVersionError
from p11.recipe.registry import UnknownModelError
from p11.templates.store import TemplateError

from .store import JobError
from .video import VideoError

INSTALL_HINT = "Run `p11 models install default` (or install the model named above)."
LOG_HINT = "Details are in ~/.cache/p11/logs/studio.log and engine.log."


def _missing_model(exc: BaseException) -> bool:
    return isinstance(exc, UnknownModelError) or isinstance(exc.__context__, UnknownModelError)


def problem_for(exc: BaseException) -> tuple[int, JobError]:
    """``(http_status, JobError)`` for ``exc``."""
    if isinstance(exc, SlotBindingError):
        return 422, JobError("recipe.slot", str(exc), "Fill in that input and try again.")
    if _missing_model(exc):
        return 409, JobError("models.missing", str(exc), INSTALL_HINT)
    if isinstance(exc, CompileError | RecipeFormatError | RecipeVersionError):
        return 422, JobError("recipe.invalid", str(exc), "Check the recipe's settings.")
    if isinstance(exc, ValidationError):
        first = exc.errors()[0] if exc.errors() else {"msg": str(exc), "loc": ()}
        where = ".".join(str(p) for p in first.get("loc", ()))
        msg = f"The recipe is not valid: {first.get('msg')}" + (f" ({where})" if where else "")
        return 422, JobError("recipe.invalid", msg, "Check the recipe's settings.")
    if isinstance(exc, UploadRejected):
        return 422, JobError("upload.rejected", str(exc), exc.hint)
    if isinstance(exc, MaskError):
        return 422, JobError("input.mask", str(exc), "Open the image in Inpaint and paint a mask.")
    if isinstance(exc, TextError):
        return 422, JobError(
            "text.invalid", str(exc), "Shorten the text or lower its size, then try again."
        )
    if isinstance(exc, SegmentationError):
        return 422, JobError(
            "background.segment", str(exc), "Press Refine and paint the mask by hand."
        )
    if isinstance(exc, (CompositeError, ImageError)):
        return 422, JobError(
            "background.composite", str(exc), "Check the photo, the background and the mask."
        )
    if isinstance(exc, GuardRefused):
        # The S5 content boundary: a neutral refusal, with nothing about how to get past it.
        return 422, JobError("face.guard", str(exc), "Pick a different image.")
    if isinstance(exc, GuardUnavailable):
        return 409, JobError("face.guard-models", str(exc), "Run `p11 models install face`.")
    if isinstance(exc, FaceError):
        return 422, JobError(
            "face.step", str(exc), "Try a clearer photo, or restore only one face."
        )
    if isinstance(exc, (ControlError, PoseError)):
        return 422, JobError("control.map", str(exc), "Try a different photo or pick a stock pose.")
    if isinstance(exc, (VideoError, FfmpegError)):
        return 422, JobError("video.invalid", str(exc), "Check the clip and the video settings.")
    if isinstance(exc, UnknownInput):
        return 422, JobError("input.missing", str(exc), "Upload the file again.")
    if isinstance(exc, TemplateError):
        return 422, JobError("template.invalid", str(exc), "")
    if isinstance(exc, GpuLockTimeout):
        return 503, JobError(
            "gpu.busy",
            str(exc),
            "Another P11 session, test or benchmark is using the GPU. Wait for it or stop it.",
        )
    if isinstance(exc, EngineError):
        return _engine(exc)
    return 500, JobError("internal", "Something went wrong inside P11.", LOG_HINT)


def _engine(exc: EngineError) -> tuple[int, JobError]:
    msg = str(exc)
    if isinstance(exc, EngineOOM):
        return 507, JobError(
            "engine.oom", msg, "Try a smaller preset or the Fast model, and close GPU-heavy apps."
        )
    if isinstance(exc, EngineInterrupted):
        return 409, JobError("job.cancelled", "The job was cancelled.", "")
    if isinstance(exc, EngineUnavailable):
        return 503, JobError("engine.unavailable", msg, "Run `p11 doctor` to see what is wrong.")
    if isinstance(exc, EngineCrashed):
        return 503, JobError(
            "engine.crashed", msg, "Run the job again. If it keeps crashing: " + LOG_HINT
        )
    if isinstance(exc, EngineTimeout):
        return 504, JobError("engine.timeout", msg, "Try a smaller preset or fewer steps.")
    if isinstance(exc, EngineValidation):
        return 422, JobError("engine.validation", msg, "A model may be missing: run `p11 doctor`.")
    if isinstance(exc, EngineExecutionError):
        return 500, JobError("engine.execution", msg, LOG_HINT)
    return 500, JobError(f"engine.{exc.kind}", msg, LOG_HINT)
