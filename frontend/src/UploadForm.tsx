import { useState, type FormEvent } from "react";

import { convertImage, downloadPdf, type ChartOptions, type Settings } from "./api";
import type { Pattern } from "./pattern";
import { PatternPreview } from "./PatternPreview";

/** The image and settings a preview was made from: the PDF is asked for with these. */
interface Source {
  image: File;
  settings: Settings;
}

type State =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "done"; pattern: Pattern; source: Source }
  | { kind: "failed"; message: string };

type Download = { kind: "idle" } | { kind: "busy" } | { kind: "failed"; message: string };

const DEFAULT_CHART: ChartOptions = { variant: "colour", paper: "A4", orientation: "portrait" };
const PAPERS: ChartOptions["paper"][] = ["A2", "A3", "A4", "A5"];
const PDF_NAME = "pattern.pdf";

/** Hand the browser a file to save, through a temporary object URL. */
function saveFile(file: Blob, name: string) {
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked a moment later: some browsers start the download after `click` returns.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function UploadForm() {
  const [image, setImage] = useState<File | null>(null);
  const [width, setWidth] = useState("100");
  const [maxColours, setMaxColours] = useState("20");
  const [fabricCount, setFabricCount] = useState("14");
  const [mergeDistance, setMergeDistance] = useState("0");
  const [minStitches, setMinStitches] = useState("0");
  const [confettiSize, setConfettiSize] = useState("0");
  const [state, setState] = useState<State>({ kind: "idle" });
  const [chart, setChart] = useState<ChartOptions>(DEFAULT_CHART);
  const [download, setDownload] = useState<Download>({ kind: "idle" });

  const busy = state.kind === "busy";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (image === null || busy) {
      return;
    }
    const settings = { width, maxColours, fabricCount, mergeDistance, minStitches, confettiSize };
    const source = { image, settings };
    setState({ kind: "busy" });
    setDownload({ kind: "idle" });
    const result = await convertImage(source.image, source.settings);
    setState(
      result.ok
        ? { kind: "done", pattern: result.pattern, source }
        : { kind: "failed", message: result.message },
    );
  }

  async function savePdf(source: Source) {
    setDownload({ kind: "busy" });
    const result = await downloadPdf(source.image, source.settings, chart);
    if (result.ok) {
      saveFile(result.pdf, PDF_NAME);
      setDownload({ kind: "idle" });
    } else {
      setDownload({ kind: "failed", message: result.message });
    }
  }

  return (
    <>
      {/* noValidate: the API checks the settings and its message is shown, not the browser's. */}
      <form noValidate onSubmit={(event) => void submit(event)}>
        <label>
          Image
          <input
            type="file"
            accept="image/*"
            onChange={(event) => setImage(event.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          Width (stitches)
          <input
            type="number"
            step="any"
            value={width}
            onChange={(event) => setWidth(event.target.value)}
          />
        </label>
        <label>
          Max colours
          <input
            type="number"
            step="any"
            value={maxColours}
            onChange={(event) => setMaxColours(event.target.value)}
          />
        </label>
        <label>
          Fabric count
          <input
            type="number"
            step="any"
            value={fabricCount}
            onChange={(event) => setFabricCount(event.target.value)}
          />
        </label>
        <label>
          Merge similar threads (colour distance)
          <input
            type="number"
            step="any"
            value={mergeDistance}
            onChange={(event) => setMergeDistance(event.target.value)}
          />
        </label>
        <label>
          Minimum stitches per thread
          <input
            type="number"
            step="any"
            value={minStitches}
            onChange={(event) => setMinStitches(event.target.value)}
          />
        </label>
        <label>
          Largest confetti cluster (stitches)
          <input
            type="number"
            step="any"
            value={confettiSize}
            onChange={(event) => setConfettiSize(event.target.value)}
          />
        </label>
        <button type="submit" disabled={image === null || busy}>
          {busy ? "Converting..." : "Convert"}
        </button>
      </form>

      {busy && <p role="status">Converting the image. This can take a few seconds.</p>}
      {state.kind === "failed" && <p role="alert">{state.message}</p>}
      {state.kind === "done" && (
        <>
          <PatternPreview pattern={state.pattern} />
          <section aria-label="PDF chart">
            <label>
              Chart
              <select
                value={chart.variant}
                onChange={(event) =>
                  setChart({ ...chart, variant: event.target.value as ChartOptions["variant"] })
                }
              >
                <option value="colour">Colour</option>
                <option value="bw">Black and white</option>
              </select>
            </label>
            <label>
              Paper
              <select
                value={chart.paper}
                onChange={(event) =>
                  setChart({ ...chart, paper: event.target.value as ChartOptions["paper"] })
                }
              >
                {PAPERS.map((paper) => (
                  <option key={paper} value={paper}>
                    {paper}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Orientation
              <select
                value={chart.orientation}
                onChange={(event) =>
                  setChart({
                    ...chart,
                    orientation: event.target.value as ChartOptions["orientation"],
                  })
                }
              >
                <option value="portrait">Portrait</option>
                <option value="landscape">Landscape</option>
              </select>
            </label>
            <button
              type="button"
              disabled={download.kind === "busy"}
              onClick={() => void savePdf(state.source)}
            >
              {download.kind === "busy" ? "Preparing PDF..." : "Download PDF"}
            </button>
            {download.kind === "failed" && <p role="alert">{download.message}</p>}
          </section>
        </>
      )}
    </>
  );
}
