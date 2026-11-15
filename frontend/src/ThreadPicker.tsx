import { useEffect, useId, useState } from "react";

import {
  getNearestThreads,
  getThreads,
  type DmcThread,
  type NearThread,
  type ThreadsResult,
} from "./api";
import { FabricSwatch, Swatch, type Rgb } from "./swatch";

/** The thread being replaced: the key entry's code, name and colour. */
export interface PickedFrom {
  code: string;
  name: string;
  rgb: Rgb;
}

/** Most search results shown at once; a narrower query finds the rest. */
const SEARCH_LIMIT = 60;

// The DMC table is fetched once per page load, whatever the number of pickers opened. A
// failed fetch is forgotten, so the next picker asks again.
let table: Promise<ThreadsResult<DmcThread>> | null = null;

function threadTable(): Promise<ThreadsResult<DmcThread>> {
  if (table === null) {
    const pending = getThreads();
    table = pending;
    void pending.then((result) => {
      if (!result.ok && table === pending) {
        table = null;
      }
    });
  }
  return table;
}

/** Forget the cached table (tests start each case from a fresh page). */
export function clearThreadTable(): void {
  table = null;
}

/**
 * The threads whose code or name contains `query` (case-insensitive): an exact code match
 * first, the rest in table order. Text matching only: nothing is ranked by colour here.
 */
export function searchThreads(
  threads: readonly DmcThread[],
  query: string,
  exclude: string,
): DmcThread[] {
  const wanted = query.trim().toLowerCase();
  if (wanted === "") {
    return [];
  }
  const matches = threads.filter(
    (thread) =>
      thread.code !== exclude &&
      (thread.code.toLowerCase().includes(wanted) || thread.name.toLowerCase().includes(wanted)),
  );
  const exact = matches.filter((thread) => thread.code.toLowerCase() === wanted);
  return [...exact, ...matches.filter((thread) => !exact.includes(thread))];
}

type Load<T> = { kind: "loading" } | { kind: "ready"; threads: T[] } | { kind: "failed"; message: string };

function fromResult<T>(result: ThreadsResult<T>): Load<T> {
  return result.ok
    ? { kind: "ready", threads: result.threads }
    : { kind: "failed", message: result.message };
}

function Choice(props: {
  thread: DmcThread;
  detail?: string;
  onPick: (thread: DmcThread) => void;
}) {
  const { thread, detail, onPick } = props;
  return (
    <li>
      <button type="button" className="thread-choice" onClick={() => onPick(thread)}>
        <Swatch rgb={thread.rgb} />
        <span className="thread-choice-code">{thread.code}</span>
        <span className="thread-choice-name">{thread.name}</span>
        {detail !== undefined && <span className="thread-choice-detail">{detail}</span>}
      </button>
    </li>
  );
}

/**
 * A dialog to choose what replaces `from`: bare fabric (the thread removed), its nearest
 * threads, as the API ranks them, then a search by code or name over the whole table.
 * `onPick` gets the thread chosen, or `null` for bare fabric.
 */
export function ThreadPicker(props: {
  from: PickedFrom;
  onPick: (thread: DmcThread | null) => void;
  onClose: () => void;
}) {
  const { from, onPick, onClose } = props;
  const titleId = useId();
  const [nearest, setNearest] = useState<Load<NearThread>>({ kind: "loading" });
  const [all, setAll] = useState<Load<DmcThread>>({ kind: "loading" });
  const [query, setQuery] = useState("");

  useEffect(() => {
    let current = true;
    void getNearestThreads(from.code).then((result) => {
      if (current) {
        setNearest(fromResult(result));
      }
    });
    void threadTable().then((result) => {
      if (current) {
        setAll(fromResult(result));
      }
    });
    return () => {
      current = false;
    };
  }, [from.code]);

  const found = all.kind === "ready" ? searchThreads(all.threads, query, from.code) : [];
  const title = `Replace DMC ${from.code} ${from.name}`;

  return (
    <div
      className="picker-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="picker"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onClose();
          }
        }}
      >
        <div className="picker-header">
          <Swatch rgb={from.rgb} />
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-button" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        <section aria-label="Remove" className="picker-section">
          <button type="button" className="thread-choice" onClick={() => onPick(null)}>
            <FabricSwatch />
            <span className="thread-choice-code">Remove</span>
            <span className="thread-choice-name">Leave bare fabric where it was</span>
          </button>
        </section>

        <section aria-label="Nearest threads" className="picker-section">
          <h3>Nearest threads</h3>
          {nearest.kind === "loading" && <p className="picker-note">Loading...</p>}
          {nearest.kind === "failed" && <p className="alert">{nearest.message}</p>}
          {nearest.kind === "ready" && (
            <ul className="thread-list">
              {nearest.threads
                .filter((thread) => thread.code !== from.code)
                .map((thread) => (
                  <Choice
                    key={thread.code}
                    thread={thread}
                    detail={`ΔE ${thread.distance.toFixed(1)}`}
                    onPick={onPick}
                  />
                ))}
            </ul>
          )}
        </section>

        <section aria-label="All threads" className="picker-section">
          <label className="field">
            <span className="field-label">Search by code or name</span>
            {/* The search is where the user starts typing once the dialog opens. */}
            {/* oxlint-disable-next-line jsx-a11y/no-autofocus */}
            <input
              type="search"
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          {all.kind === "failed" && <p className="alert">{all.message}</p>}
          {found.length > 0 && (
            <ul className="thread-list">
              {found.slice(0, SEARCH_LIMIT).map((thread) => (
                <Choice key={thread.code} thread={thread} onPick={onPick} />
              ))}
            </ul>
          )}
          {all.kind === "ready" && query.trim() !== "" && found.length === 0 && (
            <p className="picker-note">No DMC thread matches.</p>
          )}
          {found.length > SEARCH_LIMIT && (
            <p className="picker-note">{`${found.length - SEARCH_LIMIT} more: type more of the code or name.`}</p>
          )}
        </section>
      </div>
    </div>
  );
}
