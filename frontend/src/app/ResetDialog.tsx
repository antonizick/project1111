// The confirmation behind the top bar's Reset button (ADR-0048). It waits for unfinished jobs:
// a job's Cancel lives in the view that started it, so a reset now would orphan the job.

import { Dialog } from "../components/Dialog";
import { unfinishedJobs, useStudio } from "./studio";

export function ResetDialog({ onClose, onReset }: { onClose: () => void; onReset: () => void }) {
  const { state } = useStudio();
  const jobs = unfinishedJobs(state).length;
  const offline = state.connected !== true;
  return (
    <Dialog title="Reset Studio?" onClose={onClose}>
      <p>This clears forms, picked photos, masks and results in every tab.</p>
      <p className="field-help">
        Nothing on disk changes: images, uploads, models and templates stay, and so do remembered
        template inputs. The gallery keeps its images; only its filters and selection reset.
      </p>
      {jobs > 0 && (
        <p role="status">
          {jobs === 1 ? "1 job is" : `${jobs} jobs are`} still running. Reset is available when they
          finish or you cancel them.
        </p>
      )}
      {offline && (
        <p role="status">The Studio is reconnecting. Reset is available once it is back.</p>
      )}
      <div className="row">
        <span className="grow" />
        <button type="button" className="btn" data-autofocus onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-danger"
          disabled={jobs > 0 || offline}
          onClick={onReset}
        >
          Reset
        </button>
      </div>
    </Dialog>
  );
}
