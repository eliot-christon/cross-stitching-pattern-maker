import { useEffect, useId, useRef, useState } from "react";

import {
  convertImage,
  downloadPdf,
  getLimits,
  type ChartOptions,
  type DmcThread,
  type Limits,
  type Replacement,
  type SettingLimits,
  type Settings,
} from "./api";
import type { KeyEntry, Pattern } from "./pattern";
import { StitchedHeart, StitchRule } from "./motif";
import { PatternPreview } from "./PatternPreview";
import { PDF_AUTO_PREVIEW_MAX_CELLS, PdfView, type PdfNote } from "./PdfView";
import { ThreadPicker } from "./ThreadPicker";

/** The image and settings a preview was made from: the PDF is asked for with these. */
interface Source {
  image: File;
  settings: Settings;
  replacements: readonly Replacement[];
}

/** The form as it stands: the image chosen (if any) and the settings as typed. */
interface Inputs {
  image: File | null;
  settings: Settings;
  /** Thread swaps, in the order chosen: the API applies them in sequence. */
  replacements: readonly Replacement[];
}

interface Preview {
  pattern: Pattern;
  source: Source;
}

type Download = { kind: "idle" } | { kind: "busy" } | { kind: "failed"; message: string };

/** A PDF on screen: its bytes, their object URL, and what it was made from. */
interface ShownPdf {
  blob: Blob;
  url: string;
  source: Source;
  chart: ChartOptions;
}

/** A PDF the view wants: the preview's source with the chart choices. */
interface WantedPdf {
  source: Source;
  chart: ChartOptions;
  /** The preview's cells, width x height: above a bound the view waits to be asked. */
  cells: number;
}

function sameChart(a: ChartOptions, b: ChartOptions): boolean {
  const keys = Object.keys(b) as (keyof ChartOptions)[];
  return keys.every((key) => a[key] === b[key]);
}

function shows(shown: ShownPdf | null, wanted: Pick<WantedPdf, "source" | "chart">): boolean {
  return shown !== null && sameSource(shown.source, wanted.source) && sameChart(shown.chart, wanted.chart);
}

type LimitsState =
  | { kind: "loading" }
  | { kind: "ready"; limits: Limits }
  | { kind: "failed"; message: string };

const PAPERS: ChartOptions["paper"][] = ["A2", "A3", "A4", "A5"];
const PDF_NAME = "pattern.pdf";
/** How long the inputs must stay unchanged before a conversion is sent. */
const QUIET_MS = 500;

function sameSource(a: Source | null, b: Source): boolean {
  if (a === null || a.image !== b.image) {
    return false;
  }
  const keys = Object.keys(b.settings) as (keyof Settings)[];
  return (
    keys.every((key) => a.settings[key] === b.settings[key]) &&
    a.replacements.length === b.replacements.length &&
    a.replacements.every(
      (pair, i) =>
        pair.from.code === b.replacements[i]?.from.code && pair.to.code === b.replacements[i]?.to.code,
    )
  );
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
    <div role="group" aria-labelledby={labelId} className="field">
      <span id={labelId} className="field-label">
        {label}
      </span>
      <div className="field-row">
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
    return (
      <p role="status" className="status">
        Loading the settings...
      </p>
    );
  }
  if (limits.kind === "failed") {
    return (
      <p role="alert" className="alert">
        {limits.message}
      </p>
    );
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
    replacements: [],
  }));
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** A change is waiting: the quiet delay is counting, or it expired while one ran. */
  const [pending, setPending] = useState(false);
  const [running, setRunning] = useState(false);
  const [chart, setChart] = useState<ChartOptions>(() => ({
    variant: "colour",
    paper: "A4",
    orientation: "portrait",
    split: "cells",
    pagesAcross: String(ranges.pages_across.default),
    pagesDown: String(ranges.pages_down.default),
    overlap: String(ranges.overlap.default),
    centreLines: false,
  }));
  const [download, setDownload] = useState<Download>({ kind: "idle" });
  /** The key entry whose thread the picker is replacing, if it is open. */
  const [picking, setPicking] = useState<KeyEntry | null>(null);
  // The PDF view: whether it is shown, the PDF on it, and its request state.
  const [pdfVisible, setPdfVisible] = useState(false);
  const [shownPdf, setShownPdf] = useState<ShownPdf | null>(null);
  const [pdfRequest, setPdfRequest] = useState<Download>({ kind: "idle" });
  const shownRef = useRef<ShownPdf | null>(null);
  const pdfTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pdfInFlight = useRef(false);
  const pdfDue = useRef(false);
  /** What the PDF requests read: the latest preview, choices and view state. */
  const pdfLatest = useRef<{ preview: Preview | null; chart: ChartOptions; busy: boolean; visible: boolean } | null>(null);
  const pdfSeen = useRef<{ preview: Preview | null; visible: boolean }>({ preview: null, visible: false });
  /** The replacements the latest response reported as finding nothing to replace. */
  const [inactive, setInactive] = useState<ReadonlySet<Replacement>>(new Set());

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
      if (pdfTimer.current !== null) {
        clearTimeout(pdfTimer.current);
      }
      if (shownRef.current !== null) {
        URL.revokeObjectURL(shownRef.current.url);
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
    const { image, settings, replacements } = latest.current;
    if (image === null) {
      return;
    }
    const source = { image, settings, replacements };
    if (sameSource(lastSent.current, source)) {
      return;
    }
    void send(source);
  }

  async function send(source: Source) {
    lastSent.current = source;
    inFlight.current = true;
    setRunning(true);
    const result = await convertImage(
      source.image,
      source.settings,
      limits.max_upload_bytes,
      source.replacements,
    );
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
        // Marks follow the pair objects, so they stay on the right pairs after an undo.
        const ignored = result.pattern.ignored_replacements ?? [];
        setInactive(new Set(source.replacements.filter((_, i) => ignored.includes(i))));
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

  function changeReplacements(replacements: readonly Replacement[]) {
    change({ ...latest.current, replacements });
    schedule();
  }

  function replaceWith(to: DmcThread) {
    if (picking !== null) {
      const from = { code: picking.code, name: picking.name, rgb: picking.rgb };
      changeReplacements([...latest.current.replacements, { from, to }]);
    }
    setPicking(null);
  }

  /** The PDF the view wants now, or null: hidden, a conversion pending, or no preview. */
  function wantedPdf(): WantedPdf | null {
    const now = pdfLatest.current;
    if (now === null || !now.visible || now.busy || now.preview === null) {
      return null;
    }
    const { width, height } = now.preview.pattern;
    return { source: now.preview.source, chart: now.chart, cells: width * height };
  }

  function showPdf(blob: Blob, wanted: WantedPdf) {
    const previous = shownRef.current;
    const next = { blob, url: URL.createObjectURL(blob), source: wanted.source, chart: wanted.chart };
    shownRef.current = next;
    setShownPdf(next);
    if (previous !== null) {
      URL.revokeObjectURL(previous.url);
    }
  }

  function clearPdf() {
    if (shownRef.current !== null) {
      URL.revokeObjectURL(shownRef.current.url);
    }
    shownRef.current = null;
    setShownPdf(null);
    setPdfRequest({ kind: "idle" });
  }

  /** Ask for the PDF the view wants, unless it is shown; one request at a time. */
  async function requestPdf() {
    const wanted = wantedPdf();
    if (wanted === null || shows(shownRef.current, wanted)) {
      return;
    }
    if (pdfInFlight.current) {
      pdfDue.current = true;
      return;
    }
    pdfInFlight.current = true;
    setPdfRequest({ kind: "busy" });
    const { source, chart: options } = wanted;
    const result = await downloadPdf(
      source.image,
      source.settings,
      options,
      limits.max_upload_bytes,
      source.replacements,
    );
    if (!mounted.current) {
      return;
    }
    pdfInFlight.current = false;
    const now = wantedPdf();
    const current = now !== null && sameSource(now.source, source) && sameChart(now.chart, options);
    if (!current) {
      // A PDF for choices or a preview no longer shown is dropped.
      setPdfRequest({ kind: "idle" });
    } else if (result.ok) {
      showPdf(result.pdf, wanted);
      setPdfRequest({ kind: "idle" });
    } else {
      setPdfRequest({ kind: "failed", message: result.message });
    }
    if (pdfDue.current || !current) {
      pdfDue.current = false;
      const next = wantedPdf();
      if (next !== null && !tooBig(next)) {
        void requestPdf();
      }
    }
  }

  function tooBig(wanted: WantedPdf): boolean {
    return wanted.cells > PDF_AUTO_PREVIEW_MAX_CELLS;
  }

  function chooseImage(image: File | null) {
    change({ ...latest.current, image });
    // The PDF on the view belongs to the image that was there.
    clearPdf();
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
    // The PDF on the view, when it is the one asked for: saved as it is, no request.
    if (shows(shownRef.current, { source, chart }) && shownRef.current !== null) {
      saveFile(shownRef.current.blob, PDF_NAME);
      return;
    }
    setDownload({ kind: "busy" });
    const result = await downloadPdf(
      source.image,
      source.settings,
      chart,
      limits.max_upload_bytes,
      source.replacements,
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

  // Keep the PDF view in step: ask at once when it is shown or a new preview lands,
  // after the quiet delay for a change of the chart choices; never while hidden or busy.
  useEffect(() => {
    pdfLatest.current = { preview, chart, busy, visible: pdfVisible };
    const seen = pdfSeen.current;
    const atOnce = (pdfVisible && !seen.visible) || preview !== seen.preview;
    pdfSeen.current = { preview, visible: pdfVisible };
    if (pdfTimer.current !== null) {
      clearTimeout(pdfTimer.current);
      pdfTimer.current = null;
    }
    const wanted = wantedPdf();
    if (wanted === null || shows(shownRef.current, wanted) || tooBig(wanted)) {
      return;
    }
    if (atOnce) {
      void requestPdf();
    } else {
      pdfTimer.current = setTimeout(() => {
        pdfTimer.current = null;
        void requestPdf();
      }, QUIET_MS);
    }
    // requestPdf and its helpers read refs only; the effect follows these values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview, chart, busy, pdfVisible]);

  let pdfNote: PdfNote = { kind: "none" };
  if (preview !== null) {
    const current = shows(shownPdf, { source: preview.source, chart });
    const big = preview.pattern.width * preview.pattern.height > PDF_AUTO_PREVIEW_MAX_CELLS;
    if (pdfRequest.kind === "failed" && !busy) {
      pdfNote = { kind: "failed", message: pdfRequest.message };
    } else if (pdfRequest.kind === "busy" || (!current && (busy || !big))) {
      pdfNote = { kind: "making" };
    } else if (!current && big) {
      pdfNote = { kind: "generate", onGenerate: () => void requestPdf() };
    }
  }

  const { settings } = inputs;
  return (
    <div className="layout">
      <aside className="panel" aria-label="Settings">
        <StitchRule />
        <h2>Settings</h2>
        {/* noValidate: the API checks the settings and its message is shown, not the browser's. */}
        <form className="form" noValidate onSubmit={(event) => event.preventDefault()}>
          <label className="field">
            <span className="field-label">Image</span>
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
            label="Colours"
            limits={ranges.max_colours}
            value={settings.maxColours}
            onChange={(value) => changeSetting("maxColours", value)}
          />
          <label className="field">
            <span className="field-label">Fabric count</span>
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

        {inputs.replacements.length > 0 && (
          <section aria-label="Replacements" className="panel-section">
            <h2>Replacements</h2>
            <ol className="replacements">
              {inputs.replacements.map((pair, index) => (
                <li
                  // A pair may be chosen twice; its place keeps the key unique.
                  // oxlint-disable-next-line react/no-array-index-key
                  key={`${index}-${pair.from.code}-${pair.to.code}`}
                  className={inactive.has(pair) ? "replacement inactive" : "replacement"}
                >
                  <ThreadLabel thread={pair.from} />
                  <span aria-hidden="true">→</span>
                  <span className="visually-hidden">replaced by</span>
                  <ThreadLabel thread={pair.to} />
                  {inactive.has(pair) && <span className="replacement-note">not in the pattern</span>}
                  <button
                    type="button"
                    className="button"
                    aria-label={`Undo ${pair.from.code} to ${pair.to.code}`}
                    onClick={() =>
                      changeReplacements(latest.current.replacements.filter((p) => p !== pair))
                    }
                  >
                    Undo
                  </button>
                </li>
              ))}
            </ol>
            <button type="button" className="button" onClick={() => changeReplacements([])}>
              Reset replacements
            </button>
          </section>
        )}

        {preview !== null && (
          <section aria-label="PDF chart" className="panel-section">
            <h2>PDF chart</h2>
            <div className="choices">
              <label className="field">
                <span className="field-label">Chart</span>
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
              <label className="field">
                <span className="field-label">Paper</span>
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
              <label className="field">
                <span className="field-label">Orientation</span>
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
            </div>
            <div className="form chart-layout">
              <label className="field">
                <span className="field-label">Split</span>
                <select
                  value={chart.split}
                  onChange={(event) =>
                    setChart({ ...chart, split: event.target.value as ChartOptions["split"] })
                  }
                >
                  <option value="cells">By cell size (3 mm)</option>
                  <option value="pages">By pages</option>
                </select>
              </label>
              {chart.split === "pages" && (
                <>
                  <SettingField
                    label="Pages across"
                    limits={ranges.pages_across}
                    value={chart.pagesAcross}
                    onChange={(value) => setChart({ ...chart, pagesAcross: value })}
                  />
                  <SettingField
                    label="Pages down"
                    limits={ranges.pages_down}
                    value={chart.pagesDown}
                    onChange={(value) => setChart({ ...chart, pagesDown: value })}
                  />
                </>
              )}
              <SettingField
                label="Repeated rows and columns"
                limits={ranges.overlap}
                value={chart.overlap}
                onChange={(value) => setChart({ ...chart, overlap: value })}
              />
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={chart.centreLines}
                  onChange={(event) => setChart({ ...chart, centreLines: event.target.checked })}
                />
                <span>Centre lines in the PDF</span>
              </label>
            </div>
            <button
              type="button"
              className="button button-primary"
              disabled={download.kind === "busy" || busy}
              onClick={() => void savePdf(preview.source)}
            >
              {download.kind === "busy" ? "Preparing PDF..." : "Download PDF"}
            </button>
            {download.kind === "failed" && (
              <p role="alert" className="alert">
                {download.message}
              </p>
            )}
          </section>
        )}
      </aside>

      <section className="viewer-area" aria-label="Pattern">
        {busy && (
          <p role="status" className="status">
            Converting the image. This can take a few seconds.
          </p>
        )}
        {error !== null && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
        {preview !== null ? (
          <PatternPreview
            pattern={preview.pattern}
            onReplace={setPicking}
            pdfView={<PdfView url={shownPdf?.url ?? null} note={pdfNote} />}
            onShowChange={(view) => setPdfVisible(view === "pdf")}
          />
        ) : (
          <div className="empty-state">
            <StitchedHeart size={56} />
            <p>
              {inputs.image === null
                ? "Choose an image and its pattern appears here."
                : "The pattern appears here once the image is converted."}
            </p>
          </div>
        )}
      </section>
      {picking !== null && (
        <ThreadPicker
          from={{ code: picking.code, name: picking.name, rgb: picking.rgb }}
          onPick={replaceWith}
          onClose={() => setPicking(null)}
        />
      )}
    </div>
  );
}

/** A thread as the replacements list shows it: swatch, code and name. */
function ThreadLabel({ thread }: { thread: DmcThread }) {
  return (
    <span className="thread-label">
      <span
        aria-hidden="true"
        className="swatch"
        style={{ backgroundColor: `rgb(${thread.rgb.join(", ")})` }}
      />
      <span className="thread-label-code">{thread.code}</span>
      <span className="thread-label-name">{thread.name}</span>
    </span>
  );
}
