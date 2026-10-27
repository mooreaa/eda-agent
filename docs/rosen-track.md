# eda-agent work track for the Rosen controller

A Claude session ("MCP agent improvements", a9c6f9) improves eda-agent in this clone while other
sessions use the live bridge on the Rosen design. This file is the hand-off between them.

## Who does what

- **Track session (a9c6f9):** edits this clone on `main`, runs pytest, commits locally. It does not
  deploy, relaunch the loop, or call bridge tools that change or focus a document. `app_ping` is fine.
- **Live session** (whichever one is editing the design; usually "Altium access via EDA Agent MCP",
  d76da0): deploys a release at a quiet point and smoke-tests it.
- **Aaron:** approves pushes to `fork`, filing upstream issues, and any live test that edits a sheet.

## Release steps

1. Track session: finish a batch, bump `SCRIPT_VERSION` in `scripts/altium/Altium_MCP.pas` if any
   `.pas` changed, run pytest (`PYTHONPATH=$PWD/src`, dashboard tests left out; three known mainline
   failures), commit, and add a release entry below with the smoke test for each change.
2. Track session messages the live session (SendMessage) with the version and the entry.
3. Live session, between edits (sheets saved, no dialog open):
   - `eda-agent install-scripts --force`, then `eda-agent relaunch --restart`
   - `app_ping`: new `script_version`, `version_match` true
   - if Python changed: end its own `python -m eda_agent` process (parent `claude.exe`) so the
     app starts a fresh server with the new tool list
   - run the smoke tests, report back. A modal "Could not convert variant..." means a Pascal
     pattern the loop can't run: read it, press OK, `eda-agent relaunch`, and tell the track session.
4. Track session fixes anything that failed and updates `tools/altium/UPSTREAM-ISSUES.md` in the
   Rosen repo (only when no other session is committing there, or via the live session).

Rule for new Pascal: only patterns shipped code already runs (see CLAUDE.md, batch 1 lesson).

## Backlog

Item numbers are from `tools/altium/UPSTREAM-ISSUES.md`. Status is checked against the code
before work starts.

Done in 2026.10.27.102: mainline merge, 4 (refusal half), 5, 11, 22, 24, 25, 26.

| # | Item | Size | Notes |
|---|------|------|-------|
| S1 | whole-stack write: build a planned stack (copper + dielectrics, any order) through MasterLayerStack, read back, undo on mismatch | L | needs `pcb_physical_stack` proven on 25.8 first |
| S2 | the LSM showed a stack unlike the saved file (inverted, non-conductive copper): find out why | M | live, scratch board |
| E1 | ECO "Footprint Not Found" for a footprint added to a project PcbLib this session; survives reopen, re-add, project reopen. Same lib also listed under an `M:` path. Need a lookup refresh or an ECO-free footprint swap from an explicit library | M | from the Rosen session, 10-27 |
| P1 | `proj_close(save=True)` writes every member document (12 sheets, 10 unchanged): save only modified ones | S | from the Rosen session, 10-27 |
| S3 | `.stackup` export/import for the Layer Stack Manager | M | optional |
| 24b | `proj_print_all_variants` still sends `project.export_pdf` per variant (print dialog) | S | found 10-27 |
| 4b | close a phantom copy itself (needs a live probe of how to reach it) | S | 4 now refuses only |
| 17 | writable-property list per object type in `tool_guide` | M | seed from Rosen CLAUDE.md |
| 8 | template engine uses the display mode in use | M | |
| 12 | `sch_place_sheet_symbol` top edge, name/file-name position and font | M | labels may need file edit |
| 7 | `sch_place_sheet_entry` reads back real coordinates | M | |
| 18–20 | library: label formats, stale designator, polygon fill | M | |
| 14 | `lib_add_symbol_rectangle` / `lib_add_pins` honour `owner_part_id` | M | |
| 6 | stale compile: a tool that saves, closes and reloads the sheets | M | |
| 28 | schematic view zoom/mapping (`proposals/sch-view-mapping.md`) | L | needs live probing |
| 16 | harness entries | L | API may not allow |

## Releases

### 2026.10.27.103 (not deployed; includes .102)

From the Rosen session, 10-27: layer-stack writes on AD 25.8.1 and the Description key.
Smoke tests: Appendix U.
- New offline `pcb_stack_from_file`: the saved V9 stack plus the legacy chain, with disagreements
  flagged. Run it on the Rosen board's commits f1e4aeb (broken) and afe927c (restored): it fails
  the first and passes the second.
- `pcb_add_layer` / `pcb_remove_layer` / `pcb_modify_layer` dielectric fields /
  `pcb_apply_stackup_template` apply refuse without `legacy_stack_write=True`.
- `sch_set_components_parameters` `Description` writes ComponentDescription (Pascal).
- Open: whether upstream's `pcb_physical_stack` / `pcb_set_dielectric` (AD19+ MasterLayerStack)
  work on AD 25.8.1. Read-only test on a scratch board first. If they do, a whole-stack write
  (item S1) can be built on them.

### 2026.10.27.102 (not deployed)

Mainline merged to 40814ba (script 2026.10.27.33 upstream), then Rosen #4, #5, #11, #22, #24, #25
and #26. Smoke tests: `docs/RELEASE_VERIFICATION.md`, Appendix T. Python and Pascal both changed, so
the live session restarts its MCP server after the deploy.

Behaviour changes a live session will notice:
- `proj_export_pdf` / `proj_export_image(format="pdf")` refuse unless `open_print_dialog=True`.
- `app_checkpoint` refuses with several projects open unless given `project_path`.
- `app_close_document` refuses a path Altium resolves to a differently named document (an `M:`
  alias of an `R:` document included).
- `app_screenshot` PNGs are native size, half what they were.
