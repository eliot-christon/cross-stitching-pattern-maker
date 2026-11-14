import { useEffect, useId, useRef, useState } from "react";

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

/** The form as it stands: the image chosen (if any) and the settings as typed. */
interface Inputs {
  image: File | null;
  settings: Settings;
}

interface Preview {
  pattern: Pattern;
  source: Source;
}

type Download = { kind: "idle" } | { kind: "busy" } | { kind: "failed"; message: string };

type LimitsState =
  | { kind: "loading" }
  | { kind: "ready"; limits: Limits }
  | { kind: "failed"; message: string };

const DEFAULT_CHART: ChartOptions = { variant: "colour", paper: "A4", orientation: "portrait" };
const PAPERS: ChartOptions["paper"][] = ["A2", "A3", "A4", "A5"];
const PDF_NAME = "pattern.pdf";
/** How long the inputs must stay unchanged before a conversion is sent. */
const QUIET_MS = 500;

function sameSource(a: Source | null, b: Source): boolean {
  if (a === null || a.image !== b.image) {
    return false;
  }
  const keys = Object.keys(b.settings) as (keyof Settings)[];
  return keys.every((key) => a.settings[key] === b.settings[key]);
}

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

/**
 * The live form: any change of the image or a setting converts once the inputs have been
 * quiet for `QUIET_MS`. At most one conversion runs at a time; changes made meanwhile are
 * sent as one follow-up when it ends. Inputs equal to the last request sent send nothing,
 * so a failed request is not retried until something changes.
 */
function Converter({ limits }: { limits: Limits }) {
  const { settings: ranges } = limits;
  const [inputs, setInputs] = useState<Inputs>(() => ({
    image: null,
    settings: {
      width: String(ranges.width.default),
      maxColours: String(ranges.max_colours.default),
      fabricCount: "14",
      mergeDistance: String(ranges.merge_distance.default),
      minStitches: String(ranges.min_stitches.default),
      confettiSize: String(ranges.confetti_size.default),
    },
  }));
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** A change is waiting: the quiet delay is counting, or it expired while one ran. */
  const [pending, setPending] = useState(false);
  const [running, setRunning] = useState(false);
  const [chart, setChart] = useState<ChartOptions>(DEFAULT_CHART);
  const [download, setDownload] = useState<Download>({ kind: "idle" });

  // What the timers and the request callbacks read: they outlive the render that set them.
  const latest = useRef(inputs);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlight = useRef(false);
  /** The quiet delay expired while a conversion ran: send when it ends. */
  const due = useRef(false);
  const lastSent = useRef<Source | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current !== null) {
        clearTimeout(timer.current);
      }
    };
  }, []);

  const busy = pending || running;

  function cancelTimer() {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }

  /** Restart the quiet delay after a change, even a follow-up already due waits it out. */
  function schedule() {
    cancelTimer();
    due.current = false;
    setPending(true);
    timer.current = setTimeout(() => {
      timer.current = null;
      if (inFlight.current) {
        due.current = true;
      } else {
        sendIfChanged();
      }
    }, QUIET_MS);
  }

  /** Send the inputs as they stand, unless there is no image or they were the last sent. */
  function sendIfChanged() {
    due.current = false;
    setPending(false);
    const { image, settings } = latest.current;
    if (image === null) {
      return;
    }
    const source = { image, settings };
    if (sameSource(lastSent.current, source)) {
      return;
    }
    void send(source);
  }

  async function send(source: Source) {
    lastSent.current = source;
    inFlight.current = true;
    setRunning(true);
    const result = await convertImage(source.image, source.settings, limits.max_upload_bytes);
    if (!mounted.current) {
      return;
    }
    inFlight.current = false;
    setRunning(false);
    // A result for an image no longer chosen is dropped: it belongs to another pattern.
    if (source.image === latest.current.image) {
      if (result.ok) {
        setPreview({ pattern: result.pattern, source });
        setError(null);
        // A failed download's message was about the previous preview.
        setDownload((current) => (current.kind === "failed" ? { kind: "idle" } : current));
      } else {
        setError(result.message);
      }
    }
    if (due.current) {
      sendIfChanged();
    }
  }

  function change(next: Inputs) {
    latest.current = next;
    setInputs(next);
  }

  function changeSetting(key: keyof Settings, value: string) {
    change({ ...latest.current, settings: { ...latest.current.settings, [key]: value } });
    schedule();
  }

  function chooseImage(image: File | null) {
    change({ ...latest.current, image });
    // The preview, any error and any download belong to the image that was there.
    setPreview(null);
    setError(null);
    setDownload({ kind: "idle" });
    if (image === null) {
      cancelTimer();
      due.current = false;
      setPending(false);
    } else {
      schedule();
    }
  }

  async function savePdf(source: Source) {
    setDownload({ kind: "busy" });
    const result = await downloadPdf(
      source.image,
      source.settings,
      chart,
      limits.max_upload_bytes,
    );
    // The chart of an image no longer chosen is not saved: it is not the preview shown.
    if (!mounted.current || source.image !== latest.current.image) {
      return;
    }
    if (result.ok) {
      saveFile(result.pdf, PDF_NAME);
      setDownload({ kind: "idle" });
    } else {
      setDownload({ kind: "failed", message: result.message });
    }
  }

  const { settings } = inputs;
  return (
    <>
      {/* noValidate: the API checks the settings and its message is shown, not the browser's. */}
      <form noValidate onSubmit={(event) => event.preventDefault()}>
        <label>
          Image
          <input
            type="file"
            accept="image/*"
            onChange={(event) => chooseImage(event.target.files?.[0] ?? null)}
          />
        </label>
        <SettingField
          label="Width (stitches)"
          limits={ranges.width}
          value={settings.width}
          onChange={(value) => changeSetting("width", value)}
        />
        <SettingField
          label="Max colours"
          limits={ranges.max_colours}
          value={settings.maxColours}
          onChange={(value) => changeSetting("maxColours", value)}
        />
        <label>
          Fabric count
          <input
            type="number"
            step="any"
            value={settings.fabricCount}
            onChange={(event) => changeSetting("fabricCount", event.target.value)}
          />
        </label>
        <SettingField
          label="Merge similar threads (colour distance)"
          limits={ranges.merge_distance}
          value={settings.mergeDistance}
          onChange={(value) => changeSetting("mergeDistance", value)}
        />
        <SettingField
          label="Minimum stitches per thread"
          limits={ranges.min_stitches}
          value={settings.minStitches}
          onChange={(value) => changeSetting("minStitches", value)}
        />
        <SettingField
          label="Largest confetti cluster (stitches)"
          limits={ranges.confetti_size}
          value={settings.confettiSize}
          onChange={(value) => changeSetting("confettiSize", value)}
        />
      </form>

      {busy && <p role="status">Converting the image. This can take a few seconds.</p>}
      {error !== null && <p role="alert">{error}</p>}
      {preview !== null && (
        <>
          <PatternPreview pattern={preview.pattern} />
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
              disabled={download.kind === "busy" || busy}
              onClick={() => void savePdf(preview.source)}
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
