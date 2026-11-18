import { useEffect, useRef, useState } from "react";

import {
  ADJUSTMENT_LABELS,
  ADJUSTMENTS,
  changesField,
  convertImage,
  downloadPdf,
  getChartLayout,
  getLimits,
  inspectImage,
  PICTURE,
  type Adjustments,
  type Change,
  type ChartLayoutReport,
  type ChartOptions,
  type DmcThread,
  type Inspection,
  type Limits,
  type Settings,
} from "./api";
import { append, canRedo, canUndo, EMPTY_HISTORY, redo, remove, resetAll, undo, type History } from "./changes";
import { ChangesPanel } from "./ChangesPanel";
import {
  ChipChoice,
  DropZone,
  Segmented,
  SheetIcon,
  SliderField,
  Stepper,
  SwatchChoice,
  Switch,
  Tabs,
} from "./controls";
import { CropBox } from "./CropBox";
import { boxFromField, cropField, type Box } from "./crop";
import { DEFAULT_FABRIC, FABRICS } from "./fabric";
import type { KeyEntry, Pattern } from "./pattern";
import { StitchedHeart, StitchRule } from "./motif";
import { PagePicker, SectionPreview } from "./PagePicker";
import { PatternPreview } from "./PatternPreview";
import { PDF_AUTO_PREVIEW_MAX_CELLS, PdfView, type PdfNote } from "./PdfView";
import { ThreadPicker } from "./ThreadPicker";

/** The image and settings a preview was made from: the PDF is asked for with these. */
interface Source {
  image: File;
  settings: Settings;
  changes: readonly Change[];
}

/** The form as it stands: the image chosen (if any) and the settings as typed. */
interface Inputs {
  image: File | null;
  settings: Settings;
  /** Replacements and hand edits, in the order made: the API applies them in sequence. */
  changes: readonly Change[];
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
/** Sheet icons, narrow side x long side in px: each paper half the one before, as A sizes
 * are, drawn a little less unequal so A5 stays visible. */
const SHEET_PX: Record<ChartOptions["paper"], [number, number]> = {
  A2: [18, 25],
  A3: [14, 20],
  A4: [11, 16],
  A5: [9, 12],
};
/** Fabric counts offered as chips: the common Aida and evenweave counts. */
const FABRIC_COUNTS = [11, 14, 16, 18, 22, 28] as const;
const PDF_NAME = "pattern.pdf";
type Tab = "image" | "pattern" | "chart";

/** What an inspection reads besides the image: a change of any re-inspects. */
function readingKey(settings: Settings): string {
  return JSON.stringify([settings.crop, ...ADJUSTMENTS.map((field) => settings[field])]);
}
/** How long the inputs must stay unchanged before a conversion is sent. */
const QUIET_MS = 500;

function sameSource(a: Source | null, b: Source): boolean {
  if (a === null || a.image !== b.image) {
    return false;
  }
  const keys = Object.keys(b.settings) as (keyof Settings)[];
  return (
    keys.every((key) => a.settings[key] === b.settings[key]) &&
    (a.changes === b.changes || changesField(a.changes) === changesField(b.changes))
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
      readAs: PICTURE,
      crop: "",
      backgroundAsFabric: false,
      ...(Object.fromEntries(ADJUSTMENTS.map((field) => [field, String(ranges[field].default)])) as Adjustments),
    },
    changes: [],
  }));
  /** The settings tab shown: plain state, kept across widths, responses and images. */
  const [tab, setTab] = useState<Tab>("image");
  /** The changes with their undo and redo; `inputs.changes` is its list. */
  const [history, setHistory] = useState<History>(EMPTY_HISTORY);
  const historyRef = useRef(history);
  /** A pick refused, or hand edits dropped: said in the Changes panel until the next step. */
  const [changesNotice, setChangesNotice] = useState<string | null>(null);
  /** What the API found in the chosen image; null before, or if the inspection failed. */
  const [inspection, setInspection] = useState<Inspection | null>(null);
  /** "Treat as a photo": convert as a picture whatever the inspection found. */
  const [asPhoto, setAsPhoto] = useState(false);
  /** What `sendIfChanged` reads to hold back a refused upload. */
  const reading = useRef<{ inspection: Inspection | null; asPhoto: boolean }>({
    inspection: null,
    asPhoto: false,
  });
  /** The chosen image is being inspected: nothing converts until it is done. */
  const inspecting = useRef(false);
  /** The crop changed: the quiet delay ends with a new inspection, not a conversion. */
  const reinspect = useRef(false);
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
    fabricColour: DEFAULT_FABRIC,
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
  /** How the PDF would cut the preview with the chart choices, from the API. */
  const [layoutReport, setLayoutReport] = useState<ChartLayoutReport | null>(null);

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
      const { image } = latest.current;
      if (reinspect.current && image !== null) {
        void inspect(image);
      } else if (inFlight.current) {
        due.current = true;
      } else {
        sendIfChanged();
      }
    }, QUIET_MS);
  }

  /** Send the inputs as they stand, unless there is no image or they were the last sent. */
  function sendIfChanged() {
    if (inspecting.current) {
      // The inspection schedules a conversion with what it finds.
      return;
    }
    due.current = false;
    setPending(false);
    const { image, settings, changes } = latest.current;
    if (image === null || refused()) {
      return;
    }
    const source = { image, settings, changes };
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
      source.changes,
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

  function changeSettings(patch: Partial<Settings>) {
    change({ ...latest.current, settings: { ...latest.current.settings, ...patch } });
    schedule();
  }

  function changeSetting(key: Exclude<keyof Settings, "readAs" | "crop" | "backgroundAsFabric">, value: string) {
    changeSettings({ [key]: value });
  }

  /** The upload is refused and not (or cannot be) treated as a photo: nothing converts. */
  function refused(): boolean {
    const { inspection: found, asPhoto: photo } = reading.current;
    return found !== null && found.refusal !== null && (found.kind === null || !photo);
  }

  function setReading(found: Inspection | null, photo: boolean) {
    reading.current = { inspection: found, asPhoto: photo };
    setInspection(found);
    setAsPhoto(photo);
  }

  /**
   * The settings that read the image as `found` says, or as a picture when `photo` is on:
   * a grid kind fixes the width at the grid's and starts the colours at its count.
   */
  function readingSettings(found: Inspection | null, photo: boolean): Partial<Settings> {
    if (photo || found === null || found.kind === null || found.grid === null) {
      return { readAs: PICTURE };
    }
    const { grid } = found;
    return {
      readAs: found.kind,
      width: String(grid.width),
      maxColours: String(Math.max(ranges.max_colours.min, Math.min(grid.colours, ranges.max_colours.max))),
    };
  }

  /**
   * Ask the API what `image` is before it is converted, and read it that way: a grid kind
   * at its own size, a picture with the settings as they were. A refused upload converts
   * nothing until "Treat as a photo"; a failed inspection converts as a picture.
   */
  async function inspect(image: File) {
    inspecting.current = true;
    reinspect.current = false;
    setPending(true);
    const { settings: asked } = latest.current;
    const result = await inspectImage(image, limits.max_upload_bytes, asked.crop, asked);
    // Another image, crop or adjustment since: its own inspection follows.
    if (!mounted.current || latest.current.image !== image || readingKey(latest.current.settings) !== readingKey(asked)) {
      return;
    }
    inspecting.current = false;
    const found = result.ok ? result.inspection : null;
    // A new crop keeps "Treat as a photo" as it was; a new image starts with it off.
    const photo = reading.current.asPhoto;
    setReading(found, photo);
    changeSettings(readingSettings(found, photo));
  }

  /** A new crop box: the image is inspected again with it after the quiet delay. */
  function changeCrop(box: Box | null) {
    reinspect.current = true;
    changeSettings({ crop: box === null ? "" : cropField(box) });
  }

  /** An adjustment: the image changes, so it is inspected again, as for a new crop. */
  function changeAdjustments(patch: Partial<Adjustments>) {
    reinspect.current = true;
    changeSettings(patch);
  }

  function treatAsPhoto(on: boolean) {
    setReading(reading.current.inspection, on);
    const next = readingSettings(reading.current.inspection, on);
    // Off again, a grid kind's colours start from the grid; on, the colours stay as set.
    changeSettings(on ? { readAs: next.readAs } : next);
  }

  /** A step of the changes' history: the list it leaves converts after the quiet delay. */
  function changeHistory(next: History, notice: string | null = null) {
    setChangesNotice(notice);
    if (next === historyRef.current) {
      return;
    }
    historyRef.current = next;
    setHistory(next);
    change({ ...latest.current, changes: next.list });
    schedule();
  }

  /** Add a change at the end of the list, unless the list holds as many as the API takes. */
  function addChange(made: Change) {
    const { max_entries: most } = limits.changes;
    if (historyRef.current.list.length >= most) {
      changeHistory(historyRef.current, `At most ${most} changes: remove some to make another.`);
    } else {
      changeHistory(append(historyRef.current, made));
    }
  }

  function replaceWith(to: DmcThread | null) {
    if (picking !== null) {
      addChange({ op: "replace", from: { code: picking.code, name: picking.name, rgb: picking.rgb }, to });
    }
    setPicking(null);
  }

  /** Put a setting back from its chip: a crop goes as a new box would, re-inspecting. */
  function resetSetting(patch: Partial<Settings>) {
    if (patch.crop !== undefined) {
      changeCrop(null);
    } else if (ADJUSTMENTS.some((field) => patch[field] !== undefined)) {
      changeAdjustments(patch);
    } else {
      changeSettings(patch);
    }
  }

  const pickingRef = useRef(picking);
  pickingRef.current = picking;
  // Ctrl+Z and Ctrl+Shift+Z (Cmd on macOS) undo and redo the changes, except while typing
  // in a field or choosing a thread, where the keys belong to the field or the dialog.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z" || pickingRef.current !== null) {
        return;
      }
      if (typing(event.target)) {
        return;
      }
      event.preventDefault();
      changeHistory((event.shiftKey ? redo : undo)(historyRef.current));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // changeHistory reads refs only; the listener is set once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      source.changes,
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
    // A crop box belongs to the image it was drawn on.
    change({ ...latest.current, image, settings: { ...latest.current.settings, crop: "" } });
    reinspect.current = false;
    // The PDF on the view belongs to the image that was there.
    clearPdf();
    // The preview, any error, any download and what the inspection found belong to the
    // image that was there.
    setPreview(null);
    setError(null);
    setDownload({ kind: "idle" });
    setReading(null, false);
    cancelTimer();
    due.current = false;
    inspecting.current = false;
    if (image === null) {
      setPending(false);
    } else {
      void inspect(image);
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
      source.changes,
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

  const layoutWidth = preview?.pattern.width ?? 0;
  const layoutHeight = preview?.pattern.height ?? 0;
  const layoutKey = JSON.stringify([
    layoutWidth,
    layoutHeight,
    chart.paper,
    chart.orientation,
    chart.split,
    chart.pagesAcross,
    chart.pagesDown,
    chart.overlap,
  ]);
  const layoutChart = useRef(chart);
  layoutChart.current = chart;
  // Ask how the PDF would cut the preview once the layout choices have been quiet; an
  // answer for choices since changed is dropped.
  useEffect(() => {
    if (layoutWidth === 0 || layoutHeight === 0) {
      return;
    }
    let current = true;
    const timer = setTimeout(() => {
      void getChartLayout(layoutWidth, layoutHeight, layoutChart.current).then((result) => {
        if (current && mounted.current && result.ok) {
          setLayoutReport(result.report);
        }
      });
    }, QUIET_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [layoutKey, layoutWidth, layoutHeight]);

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
  /** What the latest response says each change it was sent did, by the change itself. */
  const counts = new Map<Change, number>(
    preview?.source.changes.map((entry, i) => [entry, preview.pattern.changed_cells[i] ?? 0]) ?? [],
  );
  /** A sheet icon for `paper` as `orientation` turns it. */
  const sheet = (paper: ChartOptions["paper"], orientation = chart.orientation) => {
    const [narrow, tall] = SHEET_PX[paper];
    return orientation === "portrait" ? (
      <SheetIcon width={narrow} height={tall} />
    ) : (
      <SheetIcon width={tall} height={narrow} />
    );
  };
  return (
    <div className="layout">
      <aside className="panel settings-panel" aria-label="Settings">
        <StitchRule />
        <h2>Settings</h2>
        <Tabs
          label="Settings"
          value={tab}
          onChange={setTab}
          tabs={[
            {
              value: "image",
              label: "Image",
              content: (
                // noValidate: the API checks the settings and its message is shown, not the browser's.
                <form className="form" noValidate onSubmit={(event) => event.preventDefault()}>
                  <DropZone label="Image" file={inputs.image} onChange={chooseImage} />
                  {inspection !== null && (
                    <div className="source-kind">
                      <p className="field-hint">Detected: {inspection.description}</p>
                      {inspection.warnings.map((warning) => (
                        <p key={warning} className="field-hint">
                          {warning}
                        </p>
                      ))}
                      {inspection.refusal !== null && (
                        <p role="alert" className="alert">
                          {inspection.refusal}
                        </p>
                      )}
                      {inspection.kind !== null && (inspection.kind !== PICTURE || inspection.refusal !== null) && (
                        <Switch label="Treat as a photo" checked={asPhoto} onChange={treatAsPhoto} />
                      )}
                    </div>
                  )}
                  {inputs.image !== null && inspection?.kind !== null && (
                    <CropBox file={inputs.image} box={boxFromField(settings.crop)} onChange={changeCrop} />
                  )}
                  <Switch
                    label="Background as fabric"
                    checked={settings.backgroundAsFabric}
                    onChange={(on) => changeSettings({ backgroundAsFabric: on })}
                  />

                  <h3 className="form-heading">Adjustments</h3>
                  <p className="field-hint">Applied to the image before it is read; each starts off.</p>
                  {ADJUSTMENTS.map((field) => (
                    <SliderField
                      key={field}
                      label={ADJUSTMENT_LABELS[field]}
                      limits={ranges[field]}
                      value={settings[field]}
                      onChange={(value) => changeAdjustments({ [field]: value })}
                    />
                  ))}
                </form>
              ),
            },
            {
              value: "pattern",
              label: "Pattern",
              content: (
                <form className="form" noValidate onSubmit={(event) => event.preventDefault()}>
                  <h3 className="form-heading">Size and threads</h3>
                  <SliderField
                    label="Width (stitches)"
                    limits={ranges.width}
                    value={settings.width}
                    disabled={settings.readAs !== PICTURE}
                    onChange={(value) => changeSetting("width", value)}
                  />
                  <SliderField
                    label="Colours"
                    limits={ranges.max_colours}
                    value={settings.maxColours}
                    onChange={(value) => changeSetting("maxColours", value)}
                  />
                  <ChipChoice
                    label="Fabric count"
                    presets={FABRIC_COUNTS}
                    value={settings.fabricCount}
                    onChange={(value) => changeSetting("fabricCount", value)}
                  />
                  <SwatchChoice
                    label="Fabric colour"
                    options={FABRICS}
                    value={chart.fabricColour}
                    onChange={(fabricColour) => setChart({ ...chart, fabricColour })}
                  />

                  <h3 className="form-heading">Cleanup</h3>
                  <p className="field-hint">Each at 0 is off.</p>
                  <SliderField
                    label="Merge similar threads (colour distance)"
                    limits={ranges.merge_distance}
                    value={settings.mergeDistance}
                    onChange={(value) => changeSetting("mergeDistance", value)}
                  />
                  <SliderField
                    label="Minimum stitches per thread"
                    limits={ranges.min_stitches}
                    value={settings.minStitches}
                    onChange={(value) => changeSetting("minStitches", value)}
                  />
                  <Stepper
                    label="Largest confetti cluster (stitches)"
                    limits={ranges.confetti_size}
                    value={settings.confettiSize}
                    onChange={(value) => changeSetting("confettiSize", value)}
                  />
                </form>
              ),
            },
            {
              value: "chart",
              label: "Chart",
              content: (
                <>
                {preview !== null ? (
                  <section aria-label="PDF chart" className="panel-section">
                    <div className="form">
                      <Segmented
                        legend="Chart"
                        showLegend
                        options={[
                          { value: "colour", label: "Colour" },
                          { value: "bw", label: "Black and white" },
                        ]}
                        value={chart.variant}
                        onChange={(variant) => setChart({ ...chart, variant })}
                      />
                      <Segmented
                        legend="Paper"
                        showLegend
                        className="segmented-sheets"
                        options={PAPERS.map((paper) => ({ value: paper, label: paper, icon: sheet(paper) }))}
                        value={chart.paper}
                        onChange={(paper) => setChart({ ...chart, paper })}
                      />
                      <Segmented
                        legend="Orientation"
                        showLegend
                        className="segmented-sheets"
                        options={[
                          { value: "portrait", label: "Portrait", icon: sheet("A5", "portrait") },
                          { value: "landscape", label: "Landscape", icon: sheet("A5", "landscape") },
                        ]}
                        value={chart.orientation}
                        onChange={(orientation) => setChart({ ...chart, orientation })}
                      />
                      <Segmented
                        legend="Split"
                        showLegend
                        options={[
                          { value: "cells", label: "By cell size (3 mm)" },
                          { value: "pages", label: "By pages" },
                        ]}
                        value={chart.split}
                        onChange={(split) => setChart({ ...chart, split })}
                      />
                      {chart.split === "pages" && (
                        <PagePicker
                          report={layoutReport}
                          orientation={chart.orientation}
                          across={chart.pagesAcross}
                          down={chart.pagesDown}
                          onPick={(across, down) =>
                            setChart({ ...chart, pagesAcross: String(across), pagesDown: String(down) })
                          }
                        />
                      )}
                      <SectionPreview
                        pattern={preview.pattern}
                        layout={layoutReport?.layout ?? null}
                        fabric={chart.fabricColour}
                      />
                      {layoutReport !== null && layoutReport.layout === null && layoutReport.message !== null && (
                        <p className="field-hint">{layoutReport.message}</p>
                      )}
                      <Stepper
                        label="Repeated rows and columns"
                        limits={ranges.overlap}
                        value={chart.overlap}
                        onChange={(value) => setChart({ ...chart, overlap: value })}
                        hint="Neighbouring pages share these, so their edges line up."
                      />
                      <Switch
                        label="Centre lines in the PDF"
                        checked={chart.centreLines}
                        onChange={(centreLines) => setChart({ ...chart, centreLines })}
                      />
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
                ) : (
                  <p className="field-hint">The chart choices come with the pattern.</p>
                )}
                </>
              ),
            },
          ]}
        />
      </aside>

      <ChangesPanel
        settings={settings}
        ranges={ranges}
        onReset={resetSetting}
        changes={history.list}
        counts={counts}
        canUndo={canUndo(history)}
        canRedo={canRedo(history)}
        onUndo={() => changeHistory(undo(historyRef.current))}
        onRedo={() => changeHistory(redo(historyRef.current))}
        onRemove={(entry) => changeHistory(remove(historyRef.current, entry))}
        onResetAll={() => changeHistory(resetAll(historyRef.current))}
        notice={changesNotice}
      />

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
            fabric={chart.fabricColour}
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

/** Whether a key press on `target` belongs to a field being typed in. */
function typing(target: EventTarget | null): boolean {
  if (target instanceof HTMLTextAreaElement || (target instanceof HTMLElement && target.isContentEditable)) {
    return true;
  }
  return target instanceof HTMLInputElement && ["text", "number", "search", "email", "url", "tel"].includes(target.type);
}
