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
| D1 | `pcb_get_mech_layer_names(count_primitives=True)` marks the board modified though it only reads | S | from the Rosen session, 10-27 |
| V1 | after `pcb_build_stack` (or any layer-set change) the open board keeps its old layer tabs until reopened; reopen it, or warn | S | from the Rosen session, 10-27 |
| V2 | `pcb_set_layer_visibility` says visible:true for a layer missing from the view's tab set | S | from the Rosen session, 10-27 |
| C1 | `proj_get_compile_freshness` raises "Undeclared identifier: DM_ExistingViolationCount" on AD 25.8 (modal, stops the loop) | S | from the Rosen session, 10-28; mainline code |
| U1 | ECO dialog's change grid (TdxTreeList) shows no row text to UIA and ignores scrolling; only screenshots read past page one | M | from the Rosen session, 10-28 |
| S3 | `.stackup` export/import for the Layer Stack Manager | M | optional |
| 24b | `proj_print_all_variants` still sends `project.export_pdf` per variant (print dialog) | S | found 10-27 |
| 4b | close a phantom copy itself (needs a live probe of how to reach it) | S | 4 now refuses only |
| 17 | writable-property list per object type in `tool_guide` | M | seed from Rosen CLAUDE.md |
| 8 | template engine uses the display mode in use | M | |
| 12 | `sch_place_sheet_symbol` top edge, name/file-name position and font | M | labels may need file edit |
| 7 | `sch_place_sheet_entry` reads back real coordinates | M | |
| 18-20 | library: label formats, stale designator, polygon fill | M | |
| 14 | `lib_add_symbol_rectangle` / `lib_add_pins` honour `owner_part_id` | M | |
| 6 | stale compile: a tool that saves, closes and reloads the sheets | M | |
| 28 | schematic view zoom/mapping (`proposals/sch-view-mapping.md`) | L | needs live probing |
| 16 | harness entries | L | API may not allow |

## Releases

### 2026.10.27.114 (deployed 10-28, tested on a scratch board, pushed to the fork)

Includes .113 (inserted copper made ordinary; additive and resistivity in both readers). Tested
live on a scratch copy: a build with `loss_tangent` 0.02 saved Df 0.020 on all five dielectrics;
`pcb_stack_from_file` warned `stack_manager_model_stale`; `pcb_reset_stack_manager_model` refused
while the board was open, renamed the key once closed, and after reopen and save the file had no
`STACKCUSTOMDATA` key and no findings (62.2 mil).

### 2026.10.27.110 (deployed, tested on a scratch board, pushed to the fork)

`pcb_adjust_designators`: the AdjustDesignators.pas convention inside the bridge, with tall parts at
90 degrees on top and 270 on the bottom (Aaron), the script's short-side fallback kept and listed,
read-back per part, `off_centre` reported separately. On a scratch copy of the Rosen board (322
parts): all took, a rerun gave the identical plan. `pcb_render_svg` overlay labels off by default,
magenta italic. Appendix W.

### 2026.10.27.109 (deployed, live-tested on a scratch board, pushed to the fork)

`pcb_build_stack`: a whole stack, copper and dielectrics, in one call, with read-back and an undo
(close unsaved, reopen). Built and verified live on AD 25.8.1 with the Rosen six-layer plan on a
scratch copy of the restored board; details and what AD 25.8 scripts can and cannot do to the
stack are in `docs/RELEASE_VERIFICATION.md`, Appendix V. S1 is done. S2 is mostly answered: the
Layer Stack Manager opens on a "Printed Electronics Stackup" view that lists the copper bottom up
with no dielectrics, which is what Aaron's screenshot showed.

### 2026.10.27.104 (deployed 2026-10-27, smoke-tested on scratch documents)

Smoke test, run from this checkout through the bridge on a free scratch sheet and a scratch copy
of the restored Rosen board:
- passed: `app_ping` version match; the stack, PDF and checkpoint guards refuse (checkpoint saw
  5 open projects); `pcb_stack_from_file` fails f1e4aeb and passes afe927c; `obj_zoom
  document` fits the sheet with its border (screenshot) and is refused on a board;
  `obj_deselect_all`; `app_screenshot` native 2010 x 1479.
- `pcb_physical_stack` (upstream, AD19+ MasterLayerStack) runs on AD 25.8.1 with no modal and
  matches the file reader layer for layer. So S1 can be built on it.
- not run live: the Description key (needs a placed part), the `PATH_MISMATCH` close refusal
  (needs a phantom or an aliased path).
- Known failing on mainline itself: `test_no_project_loop_looks_a_sheet_up_uncounted` (f3bd57f's
  probe listing), plus the Flask-only dashboard test.

Mainline merged again to f3bd57f (upstream script 2026.10.27.48: decimal mils in more handlers,
filtered object walks, via deletion on any layer, simulation probes), on top of .103.

### 2026.10.27.103 (includes .102)

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
