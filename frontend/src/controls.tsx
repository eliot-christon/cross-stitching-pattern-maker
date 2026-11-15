/**
 * Form controls shared by the settings panel and the viewer, each fitted to one kind of
 * value: a few named choices (segmented), a wide range (slider and number), a small range
 * (stepper), common values plus any other (chips), a colour among presets (swatches), on
 * or off (switch), and an image (drop zone). Values are kept as typed: the API checks
 * them and its message says what is wrong.
 */

import { useEffect, useId, useState, type ReactNode } from "react";

import type { SettingLimits } from "./api";

/**
 * One of a few named choices: radios shown as a row of pills, a group named by `legend`.
 * The legend is hidden (the viewer's toolbar) or shown above as a field label (the panel).
 */
export function Segmented<T extends string>(props: {
  legend: string;
  options: readonly { value: T; label: string; icon?: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  showLegend?: boolean;
  className?: string;
}) {
  const { legend, options, value, onChange, showLegend = false, className } = props;
  const name = useId();
  const labelId = useId();
  const classes = ["segmented", className].filter(Boolean).join(" ");
  const pills = options.map((option) => (
    <label key={option.value}>
      <input
        type="radio"
        name={name}
        checked={value === option.value}
        onChange={() => onChange(option.value)}
      />
      <span>
        {option.icon}
        {option.label}
      </span>
    </label>
  ));
  if (!showLegend) {
    return (
      <fieldset className={classes}>
        <legend className="visually-hidden">{legend}</legend>
        {pills}
      </fieldset>
    );
  }
  return (
    <div role="group" aria-labelledby={labelId} className="field">
      <span id={labelId} className="field-label">
        {legend}
      </span>
      <div className={`${classes} segmented-wide`}>{pills}</div>
    </div>
  );
}

/**
 * A setting over a wide range: a slider and a number field, both named by `label` and
 * showing `value`; either one edits it. The slider's range comes from the API.
 */
export function SliderField(props: {
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

/**
 * A setting over a small range: a number field between a minus and a plus button that
 * step by the limit's `step` within its range. The field takes any text, sent as typed.
 */
export function Stepper(props: {
  label: string;
  limits: SettingLimits;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  const { label, limits, value, onChange, hint } = props;
  const labelId = useId();
  const current = Number(value);
  const known = value.trim() !== "" && Number.isFinite(current);
  const step = (direction: 1 | -1) => {
    const start = known ? current : limits.default;
    const next = Math.min(limits.max, Math.max(limits.min, start + direction * limits.step));
    // A decimal step adds float noise: round to the step's own precision.
    const decimals = (String(limits.step).split(".")[1] ?? "").length;
    onChange(String(Number(next.toFixed(decimals))));
  };
  return (
    <div role="group" aria-labelledby={labelId} className="field">
      <span id={labelId} className="field-label">
        {label}
      </span>
      <div className="stepper">
        <button
          type="button"
          className="stepper-button"
          aria-label={`Decrease ${label}`}
          disabled={known && current <= limits.min}
          onClick={() => step(-1)}
        >
          −
        </button>
        <input
          type="number"
          aria-labelledby={labelId}
          min={limits.min}
          max={limits.max}
          step="any"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          className="stepper-button"
          aria-label={`Increase ${label}`}
          disabled={known && current >= limits.max}
          onClick={() => step(1)}
        >
          +
        </button>
      </div>
      {hint !== undefined && <p className="field-hint">{hint}</p>}
    </div>
  );
}

/**
 * Common values as chips, and a number field for any other, named by `label`: a chip
 * fills the field, the field takes any text.
 */
export function ChipChoice(props: {
  label: string;
  presets: readonly number[];
  value: string;
  onChange: (value: string) => void;
}) {
  const { label, presets, value, onChange } = props;
  const labelId = useId();
  const name = useId();
  return (
    <fieldset className="field chip-choice">
      <legend id={labelId} className="field-label">
        {label}
      </legend>
      <div className="chip-row">
        {presets.map((preset) => (
          <label key={preset} className="chip">
            <input
              type="radio"
              name={name}
              checked={Number(value) === preset}
              onChange={() => onChange(String(preset))}
            />
            <span>{preset}</span>
          </label>
        ))}
        <input
          type="number"
          aria-labelledby={labelId}
          step="any"
          className="chip-other"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
    </fieldset>
  );
}

/**
 * One colour among named presets, as round swatches (a radio group named by `label`),
 * plus a colour picker for any other. `value` is `#rrggbb`.
 */
export function SwatchChoice(props: {
  label: string;
  options: readonly { name: string; colour: string }[];
  value: string;
  onChange: (colour: string) => void;
}) {
  const { label, options, value, onChange } = props;
  const name = useId();
  const custom = !options.some((option) => option.colour === value);
  return (
    <fieldset className="field swatch-choice">
      <legend className="field-label">{label}</legend>
      <div className="swatch-choice-row">
        {options.map((option) => (
          <label key={option.colour} className="swatch-option" title={option.name}>
            <input
              type="radio"
              name={name}
              value={option.colour}
              checked={value === option.colour}
              onChange={() => onChange(option.colour)}
            />
            <span aria-hidden="true" style={{ backgroundColor: option.colour }} />
            <span className="visually-hidden">{option.name}</span>
          </label>
        ))}
        <label
          className={custom ? "swatch-option swatch-custom is-custom" : "swatch-option swatch-custom"}
          title="Other colour"
        >
          <input type="color" value={value} onChange={(event) => onChange(event.target.value)} />
          <span className="visually-hidden">Other colour</span>
        </label>
      </div>
    </fieldset>
  );
}

/** On or off: a checkbox drawn as a sliding switch, named by `label`. */
export function Switch(props: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const { label, checked, onChange } = props;
  return (
    <label className="switch">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="switch-track" aria-hidden="true" />
      <span>{label}</span>
    </label>
  );
}

/** A small preview of an image file, read in the page (no object URL, no request). */
function useThumbnail(file: File | null): string | null {
  // The thumbnail with the file it shows: one for another file is never shown.
  const [read, setRead] = useState<{ file: File; url: string } | null>(null);
  useEffect(() => {
    if (file === null || typeof FileReader === "undefined") {
      return;
    }
    let current = true;
    const reader = new FileReader();
    reader.onload = () => {
      const url = reader.result;
      if (current && typeof url === "string" && url.startsWith("data:image/")) {
        setRead({ file, url });
      }
    };
    reader.readAsDataURL(file);
    return () => {
      current = false;
      reader.abort();
    };
  }, [file]);
  return read !== null && read.file === file ? read.url : null;
}

/**
 * An image file, chosen from the device or dropped on the zone: a file input named by
 * `label` behind a large target that shows the chosen image.
 */
export function DropZone(props: {
  label: string;
  file: File | null;
  onChange: (file: File | null) => void;
}) {
  const { label, file, onChange } = props;
  const [over, setOver] = useState(false);
  const thumbnail = useThumbnail(file);
  return (
    <div className="field">
      <span className="field-label" aria-hidden="true">
        {label}
      </span>
      <label
        className={over ? "drop-zone is-over" : "drop-zone"}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          const dropped = event.dataTransfer.files[0];
          if (dropped !== undefined) {
            onChange(dropped);
          }
        }}
      >
        <input
          type="file"
          accept="image/*"
          aria-label={label}
          className="visually-hidden"
          onChange={(event) => onChange(event.target.files?.[0] ?? null)}
        />
        {thumbnail !== null && <img className="drop-zone-thumbnail" src={thumbnail} alt="" />}
        <span className="drop-zone-text">
          {file === null ? (
            <>
              <strong>Choose an image</strong> or drop it here
            </>
          ) : (
            <>
              <strong className="drop-zone-name">{file.name}</strong>
              <span>Choose or drop another</span>
            </>
          )}
        </span>
      </label>
    </div>
  );
}

/** A sheet of paper, `width` x `height` in px, drawn as a page with a folded corner. */
export function SheetIcon({ width, height }: { width: number; height: number }) {
  const fold = Math.min(width, height) * 0.3;
  return (
    <svg
      className="sheet-icon"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={`M0.5 0.5H${width - fold}L${width - 0.5} ${fold}V${height - 0.5}H0.5Z`}
        fill="var(--surface)"
        stroke="currentColor"
      />
      <path d={`M${width - fold} 0.5V${fold}H${width - 0.5}`} fill="none" stroke="currentColor" />
    </svg>
  );
}
