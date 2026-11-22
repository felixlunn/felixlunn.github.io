import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { dataUrl } from "../lib/dataUrl";
import { getBackend } from "./backend";
import { checkReference } from "./contract";
import FoiApp from "./FoiApp";
import type { Reference } from "./types";
import "../styles.css";
import "./foi.css";

/** The reference file, checked against the format this code reads (see contract.ts). */
function checkedReference(r: unknown): Reference {
  const problems = checkReference(r);
  const version = problems.find((p) => p.startsWith("reference.version"));
  if (version) throw new Error(version);
  if (problems.length) console.warn("foi/reference.json doesn't match what the site expects:", problems);
  return r as Reference;
}

const root = createRoot(document.getElementById("root")!);
root.render(<div className="boot">Loading FOI research…</div>);

async function load() {
  const [backend, ref, shapes] = await Promise.all([
    getBackend(),
    fetch(dataUrl("foi/reference.json")).then((r) => { if (!r.ok) throw new Error(`foi/reference.json: HTTP ${r.status}`); return r.json().then(checkedReference); }),
    fetch(dataUrl("foi/areas.geojson")).then((r) => { if (!r.ok) throw new Error(`foi/areas.geojson: HTTP ${r.status}`); return r.json() as Promise<GeoJSON.FeatureCollection>; }),
  ]);
  return { backend, ref, shapes };
}

load()
  .then(({ backend, ref, shapes }) => {
    if (!backend) {
      root.render(
        <div className="foi-gate"><div className="foi-gate-box">
          <h1>FOI research isn't set up yet</h1>
          <p className="small">This part of the site needs its own database for logins and uploads. Follow “FOI research section” in the project README,
            then add the two Supabase settings to the repository and redeploy.</p>
          <a className="small" href="./">Back to the dashboard</a>
        </div></div>,
      );
      return;
    }
    root.render(<StrictMode><FoiApp backend={backend} ref_={ref} shapes={shapes} /></StrictMode>);
  })
  .catch((err: Error) => root.render(
    <div className="boot error"><h1>Couldn't load FOI research</h1><p>{err.message}</p>
      <p>Run <code>python -m datadash.build</code> (or <code>--demo</code>) to create <code>frontend/public/data/foi/</code>.</p></div>,
  ));
