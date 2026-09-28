# Import format examples — NOT hardware designs

All part numbers and physical pins in this folder are **synthetic test data**. Do not use these examples to manufacture a board or substitute them for exports from your actual design.

- `bom.csv`: supported EasyEDA-style column names. Group references with spaces, semicolons, or quoted commas. An exact manufacturer part number and footprint are needed for comparison.
- `netlist.normalized.json`: convert your exported netlist to this neutral shape. Each physical endpoint must occur exactly once, in one net. The MVP deliberately does not guess connectivity from EasyEDA shape strings.
- `drc.normalized.json`: transcribe the complete result of your actual DRC run, recording the tool version and PCB revision. Do not remove findings simply to clear a gate. A human must also attest that DRC matches the imported board revision.

Gerber ZIP inspection recognizes common `.gtl`, `.gbl`, `.g1/.g1l`, `.g2/.g2l`, `.gts`, `.gbs`, `.gko/.gm1`, `.drl/.xln` names plus common EasyEDA layer filenames, with minimal content signatures. Recognition only establishes file inventory. Geometry and fabrication checks remain manual.
