import { useRef, useState, type PointerEvent } from "react";

import { useThumbnail } from "./controls";
import { boxFromDrag, percentRect, type Box, type Point, type Size } from "./crop";

/**
 * The chosen image, shown as large as the panel allows, to drag a crop box on: the box is
 * reported in pixels of the image (`boxFromDrag`), a new drag replaces it, and Reset
 * removes it. The page sends the box; it does nothing else with the image.
 */
export function CropBox(props: { file: File; box: Box | null; onChange: (box: Box | null) => void }) {
  const { file, box, onChange } = props;
  const url = useThumbnail(file);
  const [natural, setNatural] = useState<Size | null>(null);
  const [drag, setDrag] = useState<{ start: Point; end: Point } | null>(null);
  const image = useRef<HTMLImageElement | null>(null);

  function point(event: PointerEvent): Point {
    const rect = image.current?.getBoundingClientRect();
    return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) };
  }

  function shown(): Size {
    const rect = image.current?.getBoundingClientRect();
    return { width: rect?.width ?? 0, height: rect?.height ?? 0 };
  }

  function finish(event: PointerEvent) {
    if (drag === null || natural === null) {
      return;
    }
    setDrag(null);
    const size = shown();
    if (size.width > 0 && size.height > 0) {
      const next = boxFromDrag(drag.start, point(event), size, natural);
      if (next !== null) {
        onChange(next);
      }
    }
  }

  // While dragging, the rectangle drawn (pixels of the image as shown); otherwise the box
  // chosen, in percent of the image, so it needs no measuring.
  let outline: { left: string; top: string; width: string; height: string } | null = null;
  if (drag !== null) {
    const left = Math.min(drag.start.x, drag.end.x);
    const top = Math.min(drag.start.y, drag.end.y);
    outline = {
      left: `${left}px`,
      top: `${top}px`,
      width: `${Math.max(drag.start.x, drag.end.x) - left}px`,
      height: `${Math.max(drag.start.y, drag.end.y) - top}px`,
    };
  } else if (box !== null && natural !== null) {
    const rect = percentRect(box, natural);
    outline = {
      left: `${rect.left}%`,
      top: `${rect.top}%`,
      width: `${rect.right - rect.left}%`,
      height: `${rect.bottom - rect.top}%`,
    };
  }

  return (
    <div className="field crop">
      <span className="field-label">Crop</span>
      <p className="field-hint">
        {box === null
          ? "Drag on the image to keep only the stitched area."
          : `Keeping ${box.right - box.left} x ${box.bottom - box.top} pixels; drag again to change.`}
      </p>
      {url !== null && (
        <div
          className="crop-area"
          onPointerDown={(event) => {
            if (natural === null) {
              return;
            }
            event.currentTarget.setPointerCapture?.(event.pointerId);
            const start = point(event);
            setDrag({ start, end: start });
          }}
          onPointerMove={(event) => {
            if (drag !== null) {
              setDrag({ ...drag, end: point(event) });
            }
          }}
          onPointerUp={finish}
          onPointerCancel={() => setDrag(null)}
        >
          <img
            ref={image}
            src={url}
            alt="The chosen image, to crop"
            draggable={false}
            onLoad={(event) =>
              setNatural({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })
            }
          />
          {outline !== null && (
            <div
              className="crop-outline"
              style={outline}
            />
          )}
        </div>
      )}
      {box !== null && (
        <button type="button" className="button" onClick={() => onChange(null)}>
          Reset crop
        </button>
      )}
    </div>
  );
}
