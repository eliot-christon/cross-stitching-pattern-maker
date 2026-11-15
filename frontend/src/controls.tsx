/** Form controls shared by the settings panel and the viewer, each fitted to one kind of
 * value: a few named choices, a colour among presets, ... */

import { useId } from "react";

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
  const labelId = useId();
  const custom = !options.some((option) => option.colour === value);
  return (
    <fieldset className="field swatch-choice">
      <legend id={labelId} className="field-label">
        {label}
      </legend>
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
        <label className={custom ? "swatch-option swatch-custom is-custom" : "swatch-option swatch-custom"} title="Other colour">
          <input type="color" value={value} onChange={(event) => onChange(event.target.value)} />
          <span className="visually-hidden">Other colour</span>
        </label>
      </div>
    </fieldset>
  );
}
