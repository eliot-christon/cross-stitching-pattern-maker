import { useState, type FormEvent } from "react";

import { convertImage } from "./api";
import type { Pattern } from "./pattern";
import { PatternPreview } from "./PatternPreview";

type State =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "done"; pattern: Pattern }
  | { kind: "failed"; message: string };

export function UploadForm() {
  const [image, setImage] = useState<File | null>(null);
  const [width, setWidth] = useState("100");
  const [maxColours, setMaxColours] = useState("20");
  const [fabricCount, setFabricCount] = useState("14");
  const [state, setState] = useState<State>({ kind: "idle" });

  const busy = state.kind === "busy";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (image === null || busy) {
      return;
    }
    setState({ kind: "busy" });
    const result = await convertImage(image, { width, maxColours, fabricCount });
    setState(
      result.ok
        ? { kind: "done", pattern: result.pattern }
        : { kind: "failed", message: result.message },
    );
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
        <button type="submit" disabled={image === null || busy}>
          {busy ? "Converting..." : "Convert"}
        </button>
      </form>

      {busy && <p role="status">Converting the image. This can take a few seconds.</p>}
      {state.kind === "failed" && <p role="alert">{state.message}</p>}
      {state.kind === "done" && <PatternPreview pattern={state.pattern} />}
    </>
  );
}
