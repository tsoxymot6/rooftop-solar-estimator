import { useEffect, useState } from "react";
import { get, post, fmt } from "./api";
import { Modal } from "./ui";

export default function AnalyzeDialog({ bbox, km2, onClose, onDone }: { bbox: number[]; km2: number; onClose: () => void; onDone: (areaId: string) => void }) {
  const [name, setName] = useState("Custom area"); const [job, setJob] = useState<any>(null); const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (!job || job.state === "done" || job.state === "failed") return; const t = setInterval(() => get(`/api/jobs/${job.id}`).then(setJob).catch(() => {}), 2000); return () => clearInterval(t); }, [job]);
  useEffect(() => { if (job?.state === "done") onDone(job.area_id); }, [job?.state]);
  return <Modal title="Analyse another area" onClose={onClose}>
    {!job ? <div className="form">
      <p>This downloads open building, height and canopy data for the rectangle you drew ({fmt(km2, 2)} km²) and runs the full shadow and energy model. Expect roughly 10–20 minutes per km². Areas up to 2.5 km² are supported.</p>
      <label>Name<input value={name} onChange={e => setName(e.target.value)} /></label>
      {err && <div className="warn">{err}</div>}
      <button className="btn amber" onClick={() => post("/api/jobs", { bbox, name }).then(setJob).catch(e => setErr(e.message))}>Start analysis</button>
    </div> : <div className="form">
      <div className="progress"><i style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} /></div>
      <div><b>{job.state}</b> — {job.message}</div>
      {job.state === "failed" && <div className="warn">The analysis did not finish. Open datasets can be temporarily unavailable; no partial results were shown as real data.</div>}
    </div>}
  </Modal>;
}
