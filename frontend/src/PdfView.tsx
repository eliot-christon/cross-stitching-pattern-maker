/** Patterns of more cells than this get their PDF preview on request only: the PDF of a
 * 500 x 500 pattern takes seconds to make, and every request converts the image again. */
export const PDF_AUTO_PREVIEW_MAX_CELLS = 250_000;

/** What the PDF view shows besides the PDF itself. */
export type PdfNote =
  | { kind: "none" }
  | { kind: "making" }
  | { kind: "generate"; onGenerate: () => void }
  | { kind: "failed"; message: string };

/**
 * The PDF chart in the browser's own PDF viewer (its pages, thumbnails and zoom), with a
 * link to open it in a new tab where an embedded viewer is not available (most phones).
 */
export function PdfView({ url, note }: { url: string | null; note: PdfNote }) {
  return (
    <div className="pdf-view">
      <div className="pdf-view-bar">
        {note.kind === "making" && <p className="status">Making the PDF...</p>}
        {note.kind === "generate" && (
          <button type="button" className="button" onClick={note.onGenerate}>
            Generate preview
          </button>
        )}
        {note.kind === "failed" && <p className="alert">{note.message}</p>}
        {url !== null && (
          <a className="pdf-view-open" href={url} target="_blank" rel="noopener noreferrer">
            Open in a new tab
          </a>
        )}
      </div>
      {url === null ? (
        <div className="pdf-view-empty">
          <p>The PDF chart appears here.</p>
        </div>
      ) : (
        <iframe className="pdf-view-frame" title="PDF chart preview" src={url} />
      )}
    </div>
  );
}
