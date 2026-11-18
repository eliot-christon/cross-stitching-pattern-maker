import { ADJUSTMENT_LABELS, ADJUSTMENTS, type Change, type DmcThread, type Limits, type Settings } from "./api";
import { changeSize, toolName } from "./changes";
import { boxFromField } from "./crop";
import { FabricSwatch, Swatch } from "./swatch";

/** A setting that makes the pattern differ from the plain conversion, with its reset. */
interface Chip {
  /** The reset button's name, saying what it does: "Reset merge distance". */
  action: string;
  /** The chip's text: "Merge distance 2". */
  text: string;
  /** The settings that put it back. */
  reset: Partial<Settings>;
}

/** The settings off their `/limits` default (or off state), in the order the API applies them. */
function settingChips(settings: Settings, ranges: Limits["settings"]): Chip[] {
  const chips: Chip[] = [];
  const box = boxFromField(settings.crop);
  if (box !== null) {
    chips.push({
      action: "Remove the crop",
      text: `Crop ${box.right - box.left} × ${box.bottom - box.top} px`,
      reset: { crop: "" },
    });
  }
  for (const field of ADJUSTMENTS) {
    chips.push(...offDefault(settings[field], ranges[field].default, ADJUSTMENT_LABELS[field], field));
  }
  if (settings.backgroundAsFabric) {
    chips.push({
      action: "Turn off background as fabric",
      text: "Background as fabric",
      reset: { backgroundAsFabric: false },
    });
  }
  chips.push(
    ...offDefault(settings.mergeDistance, ranges.merge_distance.default, "Merge distance", "mergeDistance"),
    ...offDefault(settings.minStitches, ranges.min_stitches.default, "Minimum stitches", "minStitches"),
    ...offDefault(settings.confettiSize, ranges.confetti_size.default, "Confetti", "confettiSize"),
  );
  return chips;
}

/** A chip for a number setting off its default, reset to that default; none at it. */
function offDefault(value: string, initial: number, label: string, key: keyof Settings): Chip[] {
  if (Number(value) === initial) {
    return [];
  }
  return [{ action: `Reset ${label.toLowerCase()}`, text: `${label} ${value}`, reset: { [key]: String(initial) } }];
}

/**
 * Everything that makes the pattern differ from the plain conversion: the settings off
 * their default, each with a reset, then the changes in the order the API applies them,
 * each with the cells the latest response says it changed and a remove button; undo,
 * redo and reset all for the list.
 */
export function ChangesPanel(props: {
  settings: Settings;
  ranges: Limits["settings"];
  /** Put a setting back; a crop's reset carries `crop: ""`. */
  onReset: (patch: Partial<Settings>) => void;
  changes: readonly Change[];
  /** What the latest response says each change did, by the change itself; none yet: absent. */
  counts: ReadonlyMap<Change, number>;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onRemove: (change: Change) => void;
  onResetAll: () => void;
  /** Why the list changed without being asked (hand edits dropped), or a refused pick. */
  notice: string | null;
}) {
  const { changes, counts } = props;
  const chips = settingChips(props.settings, props.ranges);
  const total = chips.length + changes.length;
  return (
    <section aria-label="Changes" className="panel changes-panel">
      <details open>
        <summary>
          <h2>
            Changes <span className="changes-count">{total}</span>
          </h2>
        </summary>
        {props.notice !== null && (
          <p role="status" className="changes-notice">
            {props.notice}
          </p>
        )}
        {total === 0 && <p className="field-hint">Nothing differs from the plain conversion.</p>}
        {chips.length > 0 && (
          <ul className="setting-chips" aria-label="Settings changed">
            {chips.map((chip) => (
              <li key={chip.action} className="setting-chip">
                <span>{chip.text}</span>
                <button
                  type="button"
                  className="chip-reset"
                  aria-label={chip.action}
                  onClick={() => props.onReset(chip.reset)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        {changes.length > 0 && (
          <ol className="changes" aria-label="Edits and replacements">
            {changes.map((change, index) => {
              const count = counts.get(change);
              const inactive = count === 0;
              return (
                <li
                  // A change may be made twice; its place keeps the key unique.
                  // oxlint-disable-next-line react/no-array-index-key
                  key={index}
                  className={inactive ? "change inactive" : "change"}
                >
                  <span className="change-tool">{toolName(change)}</span>
                  <ChangeThreads change={change} />
                  {changeSize(change) !== null && <span className="change-size">{changeSize(change)}</span>}
                  {count !== undefined && (
                    <span className="change-note">
                      {inactive ? (change.op === "replace" ? "not in the pattern" : "changes nothing") : `${count} cells`}
                    </span>
                  )}
                  <button
                    type="button"
                    className="button"
                    aria-label={`Remove ${toolName(change).toLowerCase()} ${index + 1}`}
                    onClick={() => props.onRemove(change)}
                  >
                    Remove
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        <div className="changes-actions">
          <button type="button" className="button" disabled={!props.canUndo} onClick={props.onUndo}>
            Undo
          </button>
          <button type="button" className="button" disabled={!props.canRedo} onClick={props.onRedo}>
            Redo
          </button>
          <button type="button" className="button" disabled={changes.length === 0} onClick={props.onResetAll}>
            Reset all
          </button>
        </div>
      </details>
    </section>
  );
}

/** The thread(s) of a change: from and to for a replacement, the paint thread otherwise. */
function ChangeThreads({ change }: { change: Change }) {
  if (change.op === "replace") {
    return (
      <>
        <ThreadLabel thread={change.from} />
        <span aria-hidden="true">→</span>
        <span className="visually-hidden">replaced by</span>
        <ThreadLabel thread={change.to} />
      </>
    );
  }
  return <ThreadLabel thread={change.thread} />;
}

/** A thread as the changes list shows it, swatch, code and name; bare fabric for none. */
function ThreadLabel({ thread }: { thread: DmcThread | null }) {
  if (thread === null) {
    return (
      <span className="thread-label">
        <FabricSwatch />
        <span className="thread-label-code">Fabric</span>
      </span>
    );
  }
  return (
    <span className="thread-label">
      <Swatch rgb={thread.rgb} />
      <span className="thread-label-code">{thread.code}</span>
      <span className="thread-label-name">{thread.name}</span>
    </span>
  );
}
