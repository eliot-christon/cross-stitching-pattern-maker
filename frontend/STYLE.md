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

Contrast (WCAG ratio, at least 4.5:1 for every text pair):

| pair | light | dark |
|---|---|---|
| text on bg / surface / sunk | 12.6 / 14.0 / 11.4 | 14.1 / 12.5 / 15.0 |
| muted on bg / surface / sunk | 5.6 / 6.2 / 5.0 | 7.6 / 6.8 / 8.1 |
| accent on bg / surface / sunk | 5.3 / 5.8 / 4.8 | 8.6 / 7.7 / 9.2 |
| danger on bg / surface / sunk | 6.0 / 6.7 / 5.5 | 7.8 / 7.0 / 8.3 |
| on-accent on accent | 5.8 | 8.6 |

`--border` and `--stitch` are decoration, not text, and stay low (1.3-2.3:1) so they read
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

- **Where:** the stitched logo (a small heart of crosses, in the accent), the rule under
  the header, the rule at the top of each panel, the frame of the empty viewer.
- **Where not:** never over or around the pattern itself, never on the key's swatches,
  never animated, never in the accent except the logo.

## Layout

- **Desktop (800 px and wider):** the header across the top; below it, the settings panel
  (fixed width, about 340 px, scrolls with the page) on the left and the viewer area
  taking the rest on the right. The PDF choices sit at the bottom of the settings panel,
  once a pattern exists.
- **Below 800 px:** one column, stacked: header, settings panel, viewer area. No drawer.
- The page never scrolls horizontally, down to 360 px wide: wide content (the viewer, the
  key) scrolls inside its own box.
- Page gutter: `--space-4` on phones, `--space-6` on desktop; maximum content width 1600 px.

## Controls

- Each setting: its label above, then the slider and a narrow number field on one row.
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

The page with no image chosen: header with the stitched heart and title, the settings
panel, and the empty viewer framed in crosses saying where the pattern will appear.
