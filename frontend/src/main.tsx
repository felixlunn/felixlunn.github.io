import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { dataUrl } from "./lib/dataUrl";
import type { DashboardData } from "./types";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);

async function load() {
  // Both files are fetched in parallel; data.json is also preloaded from index.html.
  const [data, geo] = await Promise.all([
    fetch(dataUrl("data.json")).then((r) => {
      if (!r.ok) throw new Error(`data.json: HTTP ${r.status}`);
      return r.json() as Promise<DashboardData>;
    }),
    fetch(dataUrl("boundaries.geojson")).then((r) => {
      if (!r.ok) throw new Error(`boundaries.geojson: HTTP ${r.status}`);
      return r.json() as Promise<GeoJSON.FeatureCollection>;
    }),
  ]);
  return { data, geo };
}

root.render(<div className="boot">Loading constituency data…</div>);

load()
  .then(({ data, geo }) =>
    root.render(
      <StrictMode>
        <App data={data} geo={geo} />
      </StrictMode>,
    ),
  )
  .catch((err: Error) =>
    root.render(
      <div className="boot error">
        <h1>Couldn't load the data</h1>
        <p>{err.message}</p>
        <p>
          Run <code>python -m whips.build</code> (real data) or <code>python -m whips.build --demo</code> (synthetic, offline) to create{" "}
          <code>frontend/public/data/</code>.
        </p>
      </div>,
    ),
  );
