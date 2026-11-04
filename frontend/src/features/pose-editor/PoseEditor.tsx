// The pose editor (Phase 12): drag joints, mirror, pick a stock pose. The skeleton it shows is
// the one the ControlNet reads, so what you see is what the generation gets.

import { useCallback, useRef, useState } from "react";
import {
  COLOURS,
  JOINT_RADIUS,
  LIMBS,
  STOCK_NAMES,
  clonePerson,
  fitPerson,
  hitTest,
  mirrorPerson,
  moveJoint,
  stockPose,
  type Person,
  type PoseData,
} from "./model";

export function PoseEditor({
  data,
  onChange,
  className,
}: {
  data: PoseData;
  onChange: (next: PoseData) => void;
  className?: string;
}) {
  const svg = useRef<SVGSVGElement | null>(null);
  const [drag, setDrag] = useState<{ person: number; joint: number } | null>(null);
  const [selected, setSelected] = useState<{ person: number; joint: number } | null>(null);
  const w = data.width;
  const h = data.height;

  const at = useCallback(
    (e: React.PointerEvent): [number, number] => {
      const box = svg.current?.getBoundingClientRect();
      if (!box) return [0, 0];
      // The SVG keeps the picture's aspect (meet), so map through the drawn area.
      const scale = Math.min(box.width / w, box.height / h);
      const ox = (box.width - w * scale) / 2;
      const oy = (box.height - h * scale) / 2;
      return [(e.clientX - box.left - ox) / (w * scale), (e.clientY - box.top - oy) / (h * scale)];
    },
    [w, h],
  );

  const down = useCallback(
    (personIndex: number, e: React.PointerEvent) => {
      const [x, y] = at(e);
      const joint = hitTest(data.people[personIndex] ?? [], x, y);
      if (joint < 0) return;
      e.currentTarget.setPointerCapture(e.pointerId);
      setDrag({ person: personIndex, joint });
      setSelected({ person: personIndex, joint });
    },
    [at, data.people],
  );

  const move = useCallback(
    (personIndex: number, e: React.PointerEvent) => {
      if (!drag || drag.person !== personIndex) return;
      const [x, y] = at(e);
      const people = data.people.slice();
      people[personIndex] = moveJoint(people[personIndex] ?? [], drag.joint, x, y);
      onChange({ ...data, people });
    },
    [at, data, drag, onChange],
  );

  const up = useCallback(() => setDrag(null), []);

  const mirror = () => {
    const people = data.people.slice();
    people[0] = mirrorPerson(people[0] ?? stockPose("standing"));
    onChange({ ...data, people });
  };

  const setPose = (name: string) => {
    const people = data.people.slice();
    people[0] = fitPerson(stockPose(name), w / h);
    onChange({ ...data, people });
  };

  const addPerson = () => {
    if (data.people.length >= 8) return;
    const people = [...data.people.map(clonePerson), stockPose("standing")];
    onChange({ ...data, people });
  };

  const removePerson = (index: number) => {
    onChange({ ...data, people: data.people.filter((_, i) => i !== index) });
  };

  return (
    <div className={className ? `pose-editor ${className}` : "pose-editor"}>
      <svg
        ref={svg}
        className="pose-canvas"
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="xMidYMid meet"
        role="application"
        aria-label="Pose editor"
        onPointerMove={(e) => drag && move(drag.person, e)}
        onPointerUp={up}
        onPointerCancel={up}
      >
        <rect x={0} y={0} width={w} height={h} fill="#111" />
        {data.people.map((person, pi) => (
          <g key={pi}>
            {LIMBS.map(([a, b], i) => {
              const pa = person[a];
              const pb = person[b];
              if (!pa || !pb) return null;
              return (
                <line
                  key={i}
                  x1={pa[0] * w}
                  y1={pa[1] * h}
                  x2={pb[0] * w}
                  y2={pb[1] * h}
                  stroke={COLOURS[i]}
                  strokeWidth={Math.max(4, (4 * Math.min(w, h)) / 512)}
                  strokeLinecap="round"
                  opacity={0.6}
                />
              );
            })}
            {person.map((pt, ji) =>
              pt ? (
                <circle
                  key={ji}
                  cx={pt[0] * w}
                  cy={pt[1] * h}
                  r={JOINT_RADIUS * Math.min(w, h)}
                  fill={COLOURS[ji]}
                  stroke={selected?.person === pi && selected.joint === ji ? "#fff" : "none"}
                  strokeWidth={2}
                  onPointerDown={(e) => down(pi, e)}
                  style={{ cursor: "grab" }}
                />
              ) : null,
            )}
          </g>
        ))}
      </svg>
      <div className="pose-toolbar">
        <label>
          Stock pose
          <select
            aria-label="Stock pose"
            value=""
            onChange={(e) => e.target.value && setPose(e.target.value)}
          >
            <option value="">Pick…</option>
            {STOCK_NAMES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn btn-small" onClick={mirror}>
          Mirror
        </button>
        <button type="button" className="btn btn-small" onClick={addPerson}>
          Add person
        </button>
        {data.people.map((_, i) => (
          <button
            key={i}
            type="button"
            className="btn btn-small"
            onClick={() => removePerson(i)}
            disabled={data.people.length < 2}
          >
            Remove {i + 1}
          </button>
        ))}
      </div>
    </div>
  );
}

export function emptyPose(width = 512, height = 768, name = "standing"): PoseData {
  return {
    people: [fitPerson(stockPose(name), width / height)],
    width,
    height,
  };
}

export type { Person, PoseData };
