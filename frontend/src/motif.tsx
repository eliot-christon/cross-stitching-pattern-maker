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
        d={crossPath(crosses.map(({ x, y }) => ({ x: x / CELL, y: y / CELL })))}
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

/** Capitals 5 cells wide and 7 high ("-" and "I" 3 wide), for the stitched title. */
const LETTERS: Record<string, readonly string[]> = {
  A: [".XXX.", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"],
  C: [".XXX.", "X...X", "X....", "X....", "X....", "X...X", ".XXX."],
  E: ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"],
  H: ["X...X", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"],
  I: ["XXX", ".X.", ".X.", ".X.", ".X.", ".X.", "XXX"],
  K: ["X...X", "X..X.", "X.X..", "XX...", "X.X..", "X..X.", "X...X"],
  M: ["X...X", "XX.XX", "X.X.X", "X.X.X", "X...X", "X...X", "X...X"],
  N: ["X...X", "XX..X", "XX..X", "X.X.X", "X..XX", "X..XX", "X...X"],
  O: [".XXX.", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
  P: ["XXXX.", "X...X", "X...X", "XXXX.", "X....", "X....", "X...."],
  R: ["XXXX.", "X...X", "X...X", "XXXX.", "X.X..", "X..X.", "X...X"],
  S: [".XXXX", "X....", "X....", ".XXX.", "....X", "....X", "XXXX."],
  T: ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."],
  "-": ["...", "...", "...", "XXX", "...", "...", "..."],
  " ": ["..", "..", "..", "..", "..", "..", ".."],
};
const LETTER_HEIGHT = 7;
const LINE_GAP = 3;

/** The cells of one line of text: (x, y) of each cross, and the line's width in cells. */
function lineCells(text: string): { cells: { x: number; y: number }[]; width: number } {
  const cells: { x: number; y: number }[] = [];
  let x = 0;
  for (const [index, char] of [...text].entries()) {
    const glyph = LETTERS[char];
    if (glyph === undefined) {
      throw new Error(`no stitched letter for ${JSON.stringify(char)}`);
    }
    glyph.forEach((row, y) => {
      [...row].forEach((mark, dx) => {
        if (mark === "X") {
          cells.push({ x: x + dx, y });
        }
      });
    });
    x += (glyph[0]?.length ?? 0) + (index < text.length - 1 ? 1 : 0);
  }
  return { cells, width: x };
}

function crossPath(cells: { x: number; y: number }[]): string {
  return cells
    .map(({ x, y }) => {
      const left = x * CELL;
      const top = y * CELL;
      return `M${left + 0.8} ${top + 0.8}l2.4 2.4M${left + 3.2} ${top + 0.8}l-2.4 2.4`;
    })
    .join("");
}

/**
 * Lines of capitals stitched in crosses, each line centred and in its own thread colour
 * (`title-thread-1`, `title-thread-2`, ... classes); decorative, hidden from readers.
 */
export function StitchedTitle({ lines }: { lines: readonly string[] }) {
  const laid = lines.map(lineCells);
  const columns = Math.max(...laid.map((line) => line.width));
  const rows = lines.length * LETTER_HEIGHT + (lines.length - 1) * LINE_GAP;
  return (
    <svg
      className="stitched-title"
      viewBox={`0 0 ${columns * CELL} ${rows * CELL}`}
      aria-hidden="true"
      focusable="false"
    >
      {laid.map((line, index) => {
        const offset = Math.floor((columns - line.width) / 2);
        const top = index * (LETTER_HEIGHT + LINE_GAP);
        const cells = line.cells.map(({ x, y }) => ({ x: x + offset, y: y + top }));
        return (
          <path
            // The lines never change order.
            // oxlint-disable-next-line react/no-array-index-key
            key={index}
            className={`title-thread-${index + 1}`}
            d={crossPath(cells)}
            stroke="currentColor"
            strokeWidth="1.1"
            strokeLinecap="round"
            fill="none"
          />
        );
      })}
    </svg>
  );
}
