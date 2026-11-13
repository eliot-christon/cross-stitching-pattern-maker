# DMC stranded cotton table: source

`dmc.csv` is a byte-for-byte copy of the source file below. Nothing in it is edited:
change it only by importing a new version of the source and updating this note.

- **Source:** craft-color-codes by MakeBead (https://makebead.com)
- **File:** `data/csv/dmc-floss.csv` at commit `84dbdc26a961247f2aba58c91f314966a38e64ae`
- **URL:** https://raw.githubusercontent.com/makebead/craft-color-codes/84dbdc26a961247f2aba58c91f314966a38e64ae/data/csv/dmc-floss.csv
- **Retrieved:** 2026-11-13
- **SHA-256:** `66ebd107ace9f373edc185743d2699fc037e46c36428d72c0e8591d695aa0326`
- **Rows:** 489 threads (columns `code,name,hex,r,g,b,discontinued`)
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/. This file is licensed separately from
  the rest of the repository (Apache 2.0).
- **Credit:** Color data: craft-color-codes by MakeBead (https://makebead.com)

## Provenance

Per the source's `SOURCES.md`, the RGB values are reconstructed from the integer R/G/B
columns of earlier published DMC tables (floss.maxxmint.com and
adrianj/CrossStitchCreator), with xstitchify.com used to settle disagreements. They are
not measurements: DMC publishes no machine-readable RGB table, so any RGB for a dyed
cotton is an approximation. DMC and the thread names are trademarks of their owner; this
project is not affiliated with DMC.

## How the package reads it

- Codes keep the source's spelling (`Blanc`, `Ecru`, `B5200`, zero-padded `01`-`35`).
  Lookup by code ignores case and surrounding spaces.
- At load time, runs of whitespace inside a name collapse to one space and surrounding
  whitespace is stripped (the source has `Violet  Medium` and `Cornflower Blue  Very
  Dark`). Nothing else about a name changes, typos included. Names are therefore not unique: 158 and 791 are both
  `Cornflower Blue Very Dark` (the source tells them apart only by that double space).
  The code identifies a thread, never the name.
- The `hex` and `discontinued` columns are not used: RGB comes from `r`, `g`, `b`, and
  every row is `discontinued=false` in this version.
