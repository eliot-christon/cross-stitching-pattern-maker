/** The page's motif: crosses stitched in a small heart, and a row of crosses (STYLE.md). */

const HEART = [".XX.XX.", "XXXXXXX", "XXXXXXX", ".XXXXX.", "..XXX..", "...X..."];
const CELL = 4;

/** A heart of cross stitches, drawn in `currentColor`; decorative, hidden from readers. */
export function StitchedHeart({ size = 28 }: { size?: number }) {
  const crosses = HEART.flatMap((row, y) =>
    [...row].flatMap((mark, x) => (mark === "X" ? [{ x: x * CELL, y: y * CELL }] : [])),
  );
  const width = Math.max(...HEART.map((row) => row.length)) * CELL;
  const height = HEART.length * CELL;
  return (
    <svg
      className="logo"
      width={size}
      height={(size * height) / width}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={crosses
          .map(({ x, y }) => `M${x + 0.8} ${y + 0.8}l2.4 2.4M${x + 3.2} ${y + 0.8}l-2.4 2.4`)
          .join("")}
        stroke="currentColor"
        strokeWidth="1"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

/** A horizontal row of small crosses, used as a rule. */
export function StitchRule() {
  return <div className="stitch-rule" aria-hidden="true" />;
}
