# Style guide

The page looks like a sewing table: warm linen cloth, a few muted thread colours, rows of
small crosses as its only ornament. It stays quiet on purpose: **the pattern being made
is the most colourful thing on screen**, and nothing around it competes with it.

Every token below is a custom property in `src/theme.css`, light by default and dark
under `prefers-color-scheme: dark`. Components use the tokens, never raw values.

## Palette

| token | role | light | dark |
|---|---|---|---|
| `--bg` | page background, linen | `#f5efe3` | `#1d1a16` |
| `--surface` | panels and cards | `#fffbf3` | `#28241f` |
| `--sunk` | the viewer's well, inputs | `#ece4d4` | `#161411` |
| `--text` | body text, headings | `#2e2922` | `#eee7da` |
| `--muted` | labels' hints, secondary text | `#675e52` | `#b5ab9a` |
| `--border` | hairlines, input borders | `#ddd2bf` | `#3e3830` |
| `--stitch` | the cross-stitch motif | `#b9ab92` | `#5a5246` |
| `--accent` | the one accent, sage thread: primary button, slider, focus | `#4d6a4f` | `#a3bf98` |
| `--on-accent` | text on the accent | `#fffbf3` | `#1d1a16` |
| `--danger` | error messages | `#9a3b2c` | `#eb9a86` |
| `--danger-soft` | the faint card behind an error | `#f6e3dc` | `#3a2621` |
| `--focus` | focus ring (the accent) | `#4d6a4f` | `#a3bf98` |
| `--swatch-border` | the edge of a thread swatch, so white shows on light and black on dark | `rgb(46 41 34 / 0.35)` | `rgb(238 231 218 / 0.45)` |
| `--thread-2` | the second thread of the stitched title, ochre | `#9c6a2f` | `#d8a865` |

Contrast (WCAG ratio, at least 4.5:1 for every text pair):

| pair | light | dark |
|---|---|---|
| text on bg / surface / sunk | 12.6 / 14.0 / 11.4 | 14.1 / 12.5 / 15.0 |
| muted on bg / surface / sunk | 5.6 / 6.2 / 5.0 | 7.6 / 6.8 / 8.1 |
| accent on bg / surface / sunk | 5.3 / 5.8 / 4.8 | 8.6 / 7.7 / 9.2 |
| danger on bg / surface / sunk | 6.0 / 6.7 / 5.5 | 7.8 / 7.0 / 8.3 |
| on-accent on accent | 5.8 | 8.6 |

`--border`, `--stitch` and `--thread-2` are decoration, not text, and stay low (1.3-2.3:1) so they read
as texture. Saturation stays low everywhere; red is kept out of the chrome so the red
centre lines of the viewer (and the errors) stand out on their own.

## Type

One system stack for text, one for headings; no font file and no font host.

- `--font-text`: `system-ui, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- the page title is `--text-lg` below 800 px and `--text-xl` above
- `--font-heading`: `"Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua",
  Georgia, serif` (a bookish serif for the title and section headings only)
- scale: `--text-xs` 0.8125rem, `--text-sm` 0.875rem, `--text-md` 1rem, `--text-lg`
  1.25rem, `--text-xl` 1.75rem; line height 1.5 for text, 1.2 for headings

## Spacing, radii, shadows

- spacing: `--space-1` 4px, `--space-2` 8px, `--space-3` 12px, `--space-4` 16px,
  `--space-5` 24px, `--space-6` 32px, `--space-7` 48px
- radii: `--radius-sm` 6px (inputs, buttons), `--radius-md` 10px (cards), `--radius-lg`
  16px (panels, the viewer)
- shadows, warm and soft, never black: `--shadow-sm` for inputs and buttons, `--shadow-md`
  for panels

## The motif: rows of tiny crosses

A cross is two short strokes in an 8 px tile (`--stitch-x`), coloured `--stitch` through a
CSS mask, so it follows the theme.

- **Where:** the title, "CROSS-STITCH" over "PATTERN MAKER" stitched in 5 x 7 capitals,
  big and centred (at most 640 px wide), the first line in the accent and the second in
  `--thread-2`, the `h1` text kept for readers; the rule under the header, the rule at the
  top of each panel, the frame of the empty viewer and its small heart of crosses.
- **Where not:** never over or around the pattern itself, never on the key's swatches,
  never animated, never in the accent except the title.

## Layout

- One DOM order, settings panel, Changes panel, viewer area, placed by grid areas:
  - **1200 px and wider:** three columns: the settings panel (340 px) on the left, the
    viewer area in the middle, the Changes panel (300 px) on the right, sticky below the
    top of the window and scrolling inside itself when it is long.
  - **800 to 1199 px:** two columns: the settings panel with the Changes panel under it on
    the left, the viewer area on the right.
  - **Below 800 px:** one column, stacked: header, settings panel, Changes panel, viewer
    area. No drawer.
- The settings panel is three tabs, Image first: Image (the drop zone, what was detected,
  the crop box, background as fabric, the adjustments), Pattern (size and threads,
  fabric, cleanup) and Chart (the PDF choices and Download PDF, once a pattern exists).
  The tab shown is kept at every width and through new patterns and images.
- The Changes panel is a disclosure (open by default) headed "Changes" with a count pill:
  setting chips first (a pill on `--sunk` with a round reset button), then the ordered
  list of replacements and edits as bordered rows (tool in bold, thread swatches, size
  and cell count in `--muted`, a Remove button), an entry that did nothing dashed and
  muted, then Undo, Redo and Reset all.
- The page never scrolls horizontally, down to 360 px wide: wide content (the viewer, the
  key) scrolls inside its own box.
- Page gutter: `--space-4` on phones, `--space-6` on desktop; maximum content width 1600 px.

- The viewer area switches between the pattern and the PDF chart (Pattern / PDF, a
  segmented control first in the viewer's toolbar); the PDF is the browser's own viewer,
  framed like the pattern viewer (`--sunk`, `--radius-lg`, `--border`).

## Controls

Each kind of value has its own control, all in `src/controls.tsx`, labels above:

- a few named choices (chart variant, split, the viewer's modes): a segmented row of pills;
  paper sizes as pills with a sheet icon drawn to scale, orientation as a portrait and a
  landscape sheet
- a wide range (width, colours, merge distance, minimum stitches): a slider and a narrow
  number field on one row
- a small range (confetti, pages, repeated rows and columns): a stepper, minus and plus
  around the number
- common values plus any other (fabric count): chips, then a number field
- a colour among presets (fabric colour): round swatches, a rainbow one for any colour
- on or off (pixel art, centre lines): a sliding switch in the accent
- the image: a dashed drop zone showing the chosen image and its name
- groups shown one at a time (the settings panel's Image, Pattern and Chart): tabs, a
  full-width row of labels in `--muted`, the selected one in `--text` over a 3 px
  `--accent` underline, on a 1 px `--border` rule; arrow keys, Home and End move along them
- In each tab, settings are grouped under small muted headings (Adjustments, Size and
  threads, Cleanup).
- The primary button (Download PDF) is filled with the accent; other buttons are outlined.
- Status messages are a small muted line; errors use `--danger` text on a `--danger-soft`
  card. One status at a time.
- Focus is always visible: a 2 px `--focus` ring with a 2 px offset.

## The pattern's details

- **Summary:** the sizes as small tiles in a wrapping grid (label in `--muted` above the
  value; a second value, like the size in cm, smaller and muted).
- **Thread key:** a table on a surface card from 800 px: swatch, symbol (in the chart
  font stack), code in bold, name, then stitches and skeins right-aligned in tabular
  figures. Below 800 px each entry is a card: swatch, symbol and code on the first line,
  the name under them, then "Stitches n" and "Skeins n". It stays a table for assistive
  tech (explicit roles, the header row visually hidden), whatever the layout.
- **Swatches** show the thread's `rgb` exactly, with a `--swatch-border` edge.

## Sample screen

The page with no image chosen: the stitched title centred over the tagline, the settings
panel, and the empty viewer framed in crosses saying where the pattern will appear.
