import { useEffect, useId, useState, type FormEvent } from "react";

import {
  convertImage,
  downloadPdf,
  getLimits,
  type ChartOptions,
  type Limits,
  type SettingLimits,
  type Settings,
} from "./api";
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

type LimitsState =
  | { kind: "loading" }
  | { kind: "ready"; limits: Limits }
  | { kind: "failed"; message: string };

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

/**
 * A setting as a slider and a number field, both named by `label` and showing `value`;
 * either one edits it. The slider's range comes from the API; the number field takes any
 * text, posted as typed (the API's 422 says what is wrong).
 */
function SettingField(props: {
  label: string;
  limits: SettingLimits;
  value: string;
  onChange: (value: string) => void;
}) {
  const { label, limits, value, onChange } = props;
  const labelId = useId();
  return (
    <div role="group" aria-labelledby={labelId}>
      <span id={labelId}>{label}</span>
      <input
        type="range"
        aria-labelledby={labelId}
        min={limits.min}
        max={limits.max}
        step={limits.step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      <input
        type="number"
        aria-labelledby={labelId}
        step="any"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

/** The form, once the API has said what its settings accept. */
export function UploadForm() {
  const [limits, setLimits] = useState<LimitsState>({ kind: "loading" });

  useEffect(() => {
    let current = true;
    void getLimits().then((result) => {
      if (current) {
        setLimits(
          result.ok
            ? { kind: "ready", limits: result.limits }
            : { kind: "failed", message: result.message },
        );
      }
    });
    return () => {
      current = false;
    };
  }, []);

  if (limits.kind === "loading") {
    return <p role="status">Loading the settings...</p>;
  }
  if (limits.kind === "failed") {
    return <p role="alert">{limits.message}</p>;
  }
  return <Converter limits={limits.limits} />;
}

function Converter({ limits }: { limits: Limits }) {
  const { settings: ranges } = limits;
  const [image, setImage] = useState<File | null>(null);
  const [width, setWidth] = useState(String(ranges.width.default));
  const [maxColours, setMaxColours] = useState(String(ranges.max_colours.default));
  const [fabricCount, setFabricCount] = useState("14");
  const [mergeDistance, setMergeDistance] = useState(String(ranges.merge_distance.default));
  const [minStitches, setMinStitches] = useState(String(ranges.min_stitches.default));
  const [confettiSize, setConfettiSize] = useState(String(ranges.confetti_size.default));
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
    const result = await convertImage(source.image, source.settings, limits.max_upload_bytes);
    setState(
      result.ok
        ? { kind: "done", pattern: result.pattern, source }
        : { kind: "failed", message: result.message },
    );
  }

  async function savePdf(source: Source) {
    setDownload({ kind: "busy" });
    const result = await downloadPdf(
      source.image,
      source.settings,
      chart,
      limits.max_upload_bytes,
    );
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
        <SettingField
          label="Width (stitches)"
          limits={ranges.width}
          value={width}
          onChange={setWidth}
        />
        <SettingField
          label="Max colours"
          limits={ranges.max_colours}
          value={maxColours}
          onChange={setMaxColours}
        />
        <label>
          Fabric count
          <input
            type="number"
            step="any"
            value={fabricCount}
            onChange={(event) => setFabricCount(event.target.value)}
          />
        </label>
        <SettingField
          label="Merge similar threads (colour distance)"
          limits={ranges.merge_distance}
          value={mergeDistance}
          onChange={setMergeDistance}
        />
        <SettingField
          label="Minimum stitches per thread"
          limits={ranges.min_stitches}
          value={minStitches}
          onChange={setMinStitches}
        />
        <SettingField
          label="Largest confetti cluster (stitches)"
          limits={ranges.confetti_size}
          value={confettiSize}
          onChange={setConfettiSize}
        />
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
