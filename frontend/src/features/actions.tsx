// Follow-up actions on an image, shared by the result panel and the gallery detail view.

import { useCallback } from "react";
import { client, problemOf, saveDownload } from "../api/client";
import type { ImageEntry, Job } from "../api/types";
import { useNav, type View } from "../app/nav";
import { useStudio } from "../app/studio";
import { useToasts } from "../app/Toasts";
import { newRecipeId, upscaleRecipe } from "./generate/form";
import { useTemplateUi } from "./templates/ui";

export const LATER: Record<string, { label: string; phase: string; view: View }> = {
  inpaint: { label: "Inpaint", phase: "10", view: "inpaint" },
  background: { label: "Background", phase: "11", view: "background" },
  face: { label: "Face", phase: "12", view: "face" },
};

export function useImageActions(onJobs?: (jobs: Job[]) => void) {
  const { dispatch } = useStudio();
  const toasts = useToasts();
  const nav = useNav();
  const templates = useTemplateUi();

  const fail = useCallback(
    (e: unknown) => {
      const p = problemOf(e);
      toasts.problem(
        p,
        p.code === "models.missing" ? { label: "Models", run: () => nav.go("models") } : undefined,
      );
    },
    [toasts, nav],
  );

  const queued = useCallback(
    (jobs: Job[]) => {
      dispatch({ type: "submitted", jobs });
      onJobs?.(jobs);
    },
    [dispatch, onJobs],
  );

  return {
    fail,
    variations: (img: ImageEntry, mode: "seed" | "prompt", count = 1) =>
      client
        .variations(img.id, mode, count)
        .then((r) => queued(r.jobs))
        .catch(fail),
    upscale: (img: ImageEntry) =>
      client
        .submitJob({
          recipe: upscaleRecipe(img.id, img.prompt, { id: newRecipeId(), now: new Date() }),
          parent: img.id,
          template: img.template,
        })
        .then((job) => queued([job]))
        .catch(fail),
    download: (img: ImageEntry, strip: boolean) =>
      client.exportImage(img.id, strip).then(saveDownload).catch(fail),
    favourite: (img: ImageEntry) =>
      client
        .favourite(img.id, !img.favourite)
        .then((image) => dispatch({ type: "image", image }))
        .catch(fail),
    saveTemplate: (img: ImageEntry) => templates.saveImage(img),
    later: (key: keyof typeof LATER) => {
      const l = LATER[key];
      if (l) toasts.push({ kind: "info", message: `${l.label} arrives in Phase ${l.phase}.` });
    },
  };
}
