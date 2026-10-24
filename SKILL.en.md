---
name: fluent-24r2-skill
description: ANSYS Fluent 2024R2 (v242) end-to-end workflow — classify the physics, pick a meshing route, build the case with journals or PyFluent, drive batch and resumable long runs, post-process offline from .h5, and deliver a double-clickable .wbpj project. Covers compressible transient (explosion/shock), VOF multiphase (leakage/splashing), species transport (gas dispersion) and single-phase heat transfer. Use for .jou journals, fluent.exe command-line runs, PyFluent scripts, Fluent Meshing routes, autosave/resume watchdogs, offline .cas.h5/.dat.h5 post-processing, .wbpj generation, and failures such as gas not venting, divergence or hangs, TUI "invalid command", leftover processes, license or GPGPU errors, un-resumable autosave, and field data that will not export. Ships a case library under cases/ — search it before you start.
agent_created: true
---

# ANSYS Fluent 2024R2 General Workflow (setup → solve → post → delivery)

> 🌐 中文版 / Chinese version: [`SKILL.md`](SKILL.md) — this file is a full English translation of it.
> Both files are drop-in interchangeable: `cp SKILL.en.md SKILL.md` switches the skill to English,
> and `cp SKILL.md SKILL.md.zh-CN` preserves the Chinese one. **Keep the section numbers identical
> (§0–§12) — every file under `cases/` and `references/` cross-references them.**

A general methodology for "**build a Fluent case with journals / PyFluent / scripts, run it to completion, export results into downstream-usable data, and hand over a project the user can open themselves**".

Two principles run through the whole document:

1. **Verify first, then write the production artifact.** Fluent 24.2's TUI disagrees with the official documentation in many places; a wrong command makes the journal stall mid-way with no trace. PyFluent failures are worse — they are **silent** (no error, no effect). Probe any unverified command or API first.
2. **Search the case library before deciding for yourself.** `cases/` holds real recipes that already ran; a hit can save you days. Only when nothing matches do you fall back to the physics classification in §2 and the checklists in `references/`.

---

## 0 Entry point: identify the door first, then locate the case

**There are two doors.** Identify which one you are at before anything else — it determines the
order of every following step.

| Door | Trigger | First action |
|---|---|---|
| **A From scratch** | You only have a requirement / only geometry / "build it from nothing" | Go to 0.1 |
| **B Take over an existing case** | Someone hands you a `.cas` / `.dat` / `.msh` / `.wbpj` / journal / a pile of logs and says "modify this" | Do **0.0 (intake)** first, then fix the anchor |

### 0.0 Door B: take inventory before opening Fluent

```bash
<venv>/Scripts/python.exe scripts/inspect_case.py <case dir> --out triage.md
```

**Reads `.h5` offline** (h5py): no Fluent launch, no licence, a report in seconds. Eight sections:
assets / identity / mesh / zone inventory / fields and time / convergence evidence / warnings /
**suggested continuation stage**.

The last section names the stage to resume from (**P0–P7**). The full playbook is
`references/intake-existing-case.md`: artifact→stage table, the five questions you must answer
before touching anything, an eight-step diagnostic order for "it ran but it did not work",
six high-frequency traps, and a "what you want to change → which stage to go back to" table.

**Three iron rules for taking over:**

1. **The original is read-only.** Copy and rename first; never touch the original file or directory
   name (the case stores internal paths — renaming breaks the case/data pairing).
2. **Do not rebuild.** Change only the one place proven defective by evidence. Rebuilding throws
   away every physical judgement the other person made.
3. **Evidence order**: `.trn` transcript > residual history > file timeline > **what the other
   person told you**. "I think I set it" is not evidence; transcripts do not misremember.

> ⚠️ **A bare `.dat.h5` is the worst case**: in 2024R2 the mesh lives in the `.cas.h5`, so without
> the case you cannot even post-process offline. The only correct move is to **ask for the case
> back**, not to hack at the data file.

### 0.1–0.3 Both doors converge here

| Step | Action | Criterion / exit |
|---|---|---|
| **0.1 Classify the physics** | Map the request onto A/B/C/D in the §2 table | You can state "dominant mechanism + time scale + presence of a phase interface" in one sentence<br>**When taking over, this may already have been done by the other person — verify it, do not trust it** |
| **0.2 Search the case library** | Open `cases/README.md`, search by `class` + keyword; read the matching card | **Hit** → follow the card, changing only what its §13 "Reuse and differences" lists<br>**No hit** → select models yourself via §2 + `references/case-setup-checklist.md` |
| **0.3 Run the stage workflow** | Advance through the 8 stages of §3, each with an explicit gate | Do not advance past a failed gate. **When taking over, start at the anchor stage, but the gates before it still have to be verified** |

> ★ **Write-back duty**: once a new case runs, you must write a card into `cases/` following `cases/_TEMPLATE.md` and add a row to the index in `cases/README.md`. The value of a case library equals how many times it has been written back to.

---

## 1 Environment facts (example configuration — replace every placeholder with your own values)

| Item | Value |
|---|---|
| Fluent executable | `%AWP_ROOT242%/fluent/ntbin/win64/fluent.exe` |
| ANSYS-bundled PyFluent Python | `%AWP_ROOT242%/commonfiles/CPython/3_10/winx64/Release/python/python.exe` |
| Lightweight scripting Python | `<PY38>/python.exe` (ships PIL) |
| **Scientific Python (required for rasterizing / fitting / plotting / offline h5)** | `<venv>/Scripts/python.exe` (numpy 2.5 / scipy 1.18 / matplotlib 3.11 / h5py) |
| **PyFluent Python** | Same `<venv>` (has `ansys.fluent.core` 0.42.1); the ANSYS-bundled CPython also works |
| License | `ANSYSLMD_LICENSE_FILE=1055@localhost`; `AWP_ROOT242` is lost after reinstall/reboot — guard scripts with `os.environ.setdefault` |
| Launch form | `fluent.exe 3ddp -gu -t4 -i case.jou > case.log 2>&1` |
| **Verified version boundary** | **Only 2024R2 / v242 on Windows x64 is guaranteed.** Treat any other release as unverified — run `tests/smoke/` first; the difference list is in `references/version-compatibility.md` |

> **Placeholder convention**: `%AWP_ROOT242%` = ANSYS install root; `<PY38>` = any Python 3.8+ shipping Pillow;
> `<venv>` = a virtualenv with numpy / scipy / matplotlib / h5py; `<PROJ>` / `<CASE_DIR>` / `<OUT_DIR>`
> = project root / case directory / output directory. **Every one of these is a placeholder — never copy them literally.**

Launch arguments:

- `3ddp` = 3D double precision. **High pressure-ratio cases (e.g. 36:1) require double precision.**
- `-gu` = no GUI, journal-driven. `-i <journal>` = execute the journal.
- `-t<N>`: **use `-t4` on the command line, not `-t8`** — `-t8` raises `MPIDU_Init_shm_alloc: unable to allocate shared memory` (a Windows MPI shared-memory segment limit, unrelated to physical RAM).
- **The PyFluent form (`processor_count=N`) is not subject to that MPI limit**, but is limited by **physical memory**: 632k cells / double precision / 16 GB machine runs `processor_count=6` stably for long runs (peak ~5.8 GB); 878k cells on 6 ranks goes OOM and **crashes silently** (no dialog).
- ⚠️ `-meshing` has no effect in batch mode; the first prompt is still Solver Mode. Meshing routes: `references/meshing-routes.md`.

---

## 2 Physics classification → solution route (settle this before touching a journal)

| Class | Criterion | Solver / models | Time scale | Typical time step |
|---|---|---|---|---|
| **A Compressible transient** | Pressure gradient / inertia dominated, Mach ≳ 0.3, millisecond scale (explosion, shock, high-pressure release) | **Density-based (implicit) + ideal gas + second-order transient**, **gravity off** | ms | 1e-4 ~ 5e-4 s |
| **B High-density-ratio multiphase** | Phase interface present, Fr/We dominated, second scale (liquid leakage, melt splashing, free surface) | **Pressure-based + VOF (implicit) + Implicit Body Force**, PISO | s | 1e-4 ~ 5e-3 s |
| **C Species transport / dispersion** | No phase interface; the deliverable is a concentration field (toxic / flammable gas, flue gas) | **Pressure-based + Species Transport + Realizable k-ε** | ten seconds ~ minutes | 5e-3 ~ 1e-2 s |
| **D Single-phase flow / heat transfer** | No interface, no species, steady or slow transient (wind field, heat exchange, drag) | Pressure-based SIMPLE / Coupled; energy and radiation as required | steady or long transient | per CFL |

### Four selection rules

1. **Millisecond shock → density-based + ideal gas.** A pressure-based solver cannot capture shocks or expansion waves correctly. **Also leave gravity off**: over 0.1 s the gravity-induced velocity increment is about 1 m/s, under 0.3% of the shock speed.
2. **Second-scale high-density-ratio multiphase → pressure-based + VOF + implicit body force.** With a density ratio > 1000, skipping implicit body force makes interface pressure oscillate; use **Compressive / Modified HRIC** for the interface and **never second-order upwind** (it smears the interface).
   - An excessively large density ratio still diverges pathologically (measured: ρ=3500, ratio 2857 — Courant jumps from 0.6 to 210 at step 8–9, and **turning off surface tension or shrinking the time step does not help**). **Lowering the density ratio** (3500 → 1200) does help; trajectory and splashing are Fr-dominated so the physical picture is unchanged — but the delivery document must state that this is a **numerical compromise**.
   - **Do not use `geo-reconstruct` with implicit VOF** (it crashes the process in 24.2, measured). Fixed combination: `PISO + compressive + PRESTO! + second-order upwind + implicit body force`.
   - **Surface tension is off by default**; decide with `Bo = ρgL²/σ`. When Bo ≫ 1 it is physically negligible, and at high density ratio CSF generates parasitic velocities that cause divergence.
3. **Second-scale gas dispersion → pressure-based + species transport.** Simpler than VOF (no interface), and the output is directly a concentration field (`molef-<species>`). **Heavy gas requires gravity on** (sinking is the dominant mechanism) — the opposite of class A.
4. **The mesh must match the physical form.** Changing the physical model changes the mesh requirement, and the existing mesh usually cannot be reused (a 0.15 m DPM mesh smears a Ø150 mm liquid slug). Spend 30 seconds up front checking whether the mesh can resolve the feature scale:
   ```python
   R_min = 5 * h            # take a 10-cell diameter
   V_min = 4/3*pi*R_min**3  # designed injected volume << V_min ⇒ this mesh cannot run this case
   ```

---

## 3 Standard workflow (8 stages, gate at every stage)

> Every gate is in the table. **A failed gate means no progress** — this is far cheaper than explaining the results afterwards.

| Stage | What you do | Output | **Gate criterion** |
|---|---|---|---|
| **P0 Freeze the acceptance basis** | Define the acceptance quantities, threshold sources, datum (where measurement starts), slice heights, time window; pull baseline magnitudes from the case library | A one-page "acceptance basis" (written into the README) | Every delivered number answers "unit / datum / who set the threshold / which time window" |
| **P1 Mesh** | Choose a route per `references/meshing-routes.md`; refine critical regions | `.msh.h5` or `.cgns` | `/mesh/check` minimum volume > 0; the mesh resolves the feature scale (rule 4) |
| **P2 Build the case** | Verify each command with a probe journal → production journal / PyFluent script → **write-case immediately after any zone change** | `*_setup.cas.h5` | The log shows `N cell zone, M face zones`; the zone list (ID / type) is recorded |
| **P3 Trial run self-check** | Run 10–50 steps; inspect the t=0 field; compare magnitudes against the baseline | Trial log + criteria table | ① t=0 field check passes (injected / patched amounts match) ② step 1 emits a `Flow time` line ③ magnitudes are on the same order as the baseline |
| **P4 Automated long run** | Script-driven batch + autosave + segmented resume + watchdog (§4) | Unattended, fully written dat frames | `time step` in `.trn` keeps advancing; auto_save has written at least one frame to disk |
| **P5 Post-processing** | **Prefer offline `.h5` reads**; start Fluent only when necessary (§7) | CSV / contours / field data / outlines | **Digit-for-digit agreement** with Fluent's own reported values; basis written into metadata |
| **P6 Delivery** | Data + contours + **`.wbpj` project** (§8) + basis notes | Delivery package | Two criteria: static inspection + headless read-back (the 4th item of §8) |
| **P7 Write back the case** | Write a card per `cases/_TEMPLATE.md` + update the index in `cases/README.md` | New case card | The next person can **reproduce the case from the card alone**; `scripts/check_cases.py` reports zero errors |

**Three rules that span the whole run:**

- **The order in P2 cannot be swapped**: `read-case → check → fix zone types → write case`. A mesh whose zone types were edited is no longer the original mesh; not saving the case makes every subsequent autosave un-resumable.
- **The t=0 check in P3 is the cheapest gate there is.** Measured cost of skipping it: patching injected only 24% of the design value (per-register calls do not accumulate), wasting 4.3 h of long run; saving one frame at t=0 and checking `ΣαV` offline would have caught it in 5 minutes.
- **Do not declare "it ran" before P6.** A `*.cas.h5` / `*.dat.h5` produced by a script is not a finished delivery — the user cannot open or modify it.

---

## 4 Automation: let the scripts finish the job (P4 in detail)

### 4.1 Three drive forms — pick as needed

| Form | Use when | Entry |
|---|---|---|
| **Direct journal** | The command chain is fixed and needs no decisions from intermediate results | `scripts/run_fluent_journal.py` |
| **PyFluent script** | Branching is needed (read back a value, patch in a loop, retry on failure, import a mesh) | `pyfluent.launch_fluent(...)`, see `references/pyfluent-vof-sputtering.md` |
| **Outer scheduler** | Multi-case batches, serial queueing, memory guard, automatic post-processing | A project-local `run_serial_*.py`-style script |

**Key judgement**: **always import CGNS meshes through PyFluent with retries, never through `fluent.exe -i journal`**. Measured: the same CGNS file always dies right after `Importing` on the journal path (no stack, no `Opening library` line), and succeeds on the first attempt via PyFluent — the "the file itself is broken" conclusion drawn back then was **wrong**.

### 4.2 Long runs: segmented resume + watchdog

1. Enable autosave while solving: `/file/auto-save/data-frequency 200` + `/file/auto-save/root-name "<prefix>"` (**bare file name only, no directory**).
2. Have the script scan the directory for the newest `*.dat.h5` number as the checkpoint (**take the last run of digits**, not the first — the `5` in the `.h5` extension makes step 600 look like step 5).
3. Resume = `read-case(setup)` → `read-data(newest checkpoint)` → `dual-time-iterate N 20` → `write-data`. **Never call `standard_initialize`** (the flow field comes from the data file; initializing wipes it).
4. Resume only 400–700 steps per segment (~45–80 min) and exit deliberately with the archive written ⇒ **re-triggerable, and inherently tolerant of being killed or crashing**.
5. An external periodic trigger (Windows Task Scheduler) acts as the watchdog: skip if a solver process is already running, otherwise resume the next segment; call post-processing once the total step count is reached.

> ⚠️ **Ending the session kills the whole child process tree.** `DETACHED_PROCESS` / `BREAKAWAY` / `ShellExecute` were **all measured to be killed** inside an agent session. **The standard practice on this machine: write a .bat and ask the user to double-click it.** Liveness must be judged **in a separate tool call** (an "it's running" observation inside the same call is not evidence).
> Details and every pitfall (`IgnoreNew` blocking, Ctrl+C taking down the process tree, `python.exe` flashing a black window every 15 min, half-written archives): `references/auto-resume-and-guard.md`.

### 4.3 Deciding "is it actually computing": three kinds of evidence only

| Evidence | Refresh rate | Use |
|---|---|---|
| **`work/fluent-<timestamp>-<pid>.trn`** | Real time (written by Fluent itself) | ★ First choice. Read `Flow time = X, time step = N` for the true step count |
| Scheduler script's stdout log | Python blocks at 8 KB; measured up to 3 min before flushing | **Relying on it alone misreads "healthy progress" as "stuck"** |
| `*_auto-*-NNNNNN.dat.h5` | Every N steps | Archive/resume basis, but far too coarse |

- **Do not infer step count from the number of iteration lines**: the residual table prints one line every 10 iterations ⇒ `iter_lines ≈ steps × 25 / 10`, measured off by a factor of 2.5.
- **The solve log is mixed-encoding** (OEM on the Fluent side, UTF-8 on the script side), so Chinese patterns match nothing and silently return 0 lines. **Always anchor with ASCII** (`grep -a '>> '`, `grep -a '\[OK\]'`) and pass `-a`.
- **Do not use `tasklist | grep` to judge processes** (the Chinese locale mangles the encoding; measured to return nothing). Use Python `subprocess` to call `tasklist /FO CSV` + `csv.reader`, or simply use file mtime.
- **Do not call PowerShell from Bash** (blocked by security policy), and the PowerShell tool **does not echo stdout on this machine** ⇒ get process / memory info through Python `subprocess` calling native executables.

### 4.4 Script inventory (shipped with this skill)

| Script | Purpose |
|---|---|
| `scripts/inspect_case.py` | **Intake triage**: reads `.cas.h5` / `.dat.h5` / `.msh.h5` offline and reports mesh / zones / fields / residuals / pairing warnings plus the suggested resume stage. No Fluent launch, no licence (§0.0) |
| `scripts/run_fluent_journal.py` | Run a journal, persist the log, echo key lines and the exit code |
| `scripts/make_render_journal.py` | Journal that renders multi-frame contours serially (built-in re-render, fixed colour scale) |
| `scripts/export_field_journal.py` | Journal that batch-exports multi-frame, multi-variable field data (`.xyz`) |
| `scripts/rasterize_field_to_grid.py` | Field data → raster mask wide table / long table (with denoising and the nearest-neighbour basis) |
| `scripts/monitor_to_csv.py` | Monitor text → time-series CSV (first peak / arrival time; can drop reflection peaks) |
| `scripts/auto_resume.py` | Generate and launch the segmented-resume journal |
| `scripts/check_cases.py` | Case-library consistency check: front matter / controlled vocabulary / index agreement / links / assets |
| `scripts/audit_sensitive.py` | **Pre-publication** audit: local absolute paths / home directories / e-mails / IPs / organisation names; accepts a custom term list in `scripts/audit_terms.local.txt` |

---

## 5 Verified TUI commands

Full list, interactive answer sequences and the deprecated-command table: `references/tui-commands.md`. Below is a complete **compressible-transient** skeleton:

```text
/file/read-case "path/case.msh.h5"
/mesh/check
/define/boundary-conditions/zone-type 714 interior
/define/models/solver/density-based
no
/define/models/energy yes
no
no
no
yes
/define/materials/change-create air air yes ideal-gas
no
no
no
no
no
no
/define/models/unsteady-2nd-order
yes
/solve/set/time-step 0.0005
/solve/initialize/set-defaults/pressure 101325
/solve/initialize/set-defaults/temperature 298
/solve/initialize/initialize-flow
/solve/patch
707
()
pressure
3600000
/solve/dual-time-iterate 200 20
/file/write-case "path/final.cas.h5"
ok
/exit
yes
```

Key points:

- **Use hyphens in command names** (`unsteady-2nd-order`, `plane-point-n-normal`), not underscores.
- **The TUI cannot resolve zone names containing colons** (`air_ambient:1:707`); always use numeric IDs.
- `/solve/set/time-step` only takes effect if executed **after** switching to transient.
- `/solve/patch` is interactive: zone ID first, then `()` to end the list, then variable name and value.
- Overwriting an existing file prompts `OK to overwrite?`; add an `ok` line in the journal, otherwise **subsequent lines get eaten as answers**.
- `read-case-data` does not accept two paths; split it into `read-case` + `read-data`.
- Model-enabling chains for VOF / species transport: `references/tui-commands.md` §3.

---

## 6 Monitoring and contours

### 6.1 Probe sampling (recorded automatically while solving)

`/report/surface-integrals/vertex-avg` and its variants **all report invalid command** in the 24.2 build. The only reliable route is datamodel-driven report-definitions + report-files:

```text
/surface/point-surface p5 6.75 0 0
/solve/report-definitions/add mon_p5 surface-vertexavg field pressure surface-names (p5) q q q
/solve/report-files/add mon_file report-defs (mon_p5) frequency 1 frequency-of time-step file-name "path/mon.txt" q q
```

Three hard rules:

1. **`point-surface` must never appear in a solver journal** — a point-surface existing during the solve triggers `Update_Boundary_Velocity → porous_interface_mom_source → SIGSEGV`. Create it in the **post-processing** stage only.
2. When the `report-files` target already exists, the overwrite prompt eats subsequent journal lines and the actual output becomes `<name>_1_1.txt`. **Delete old files before each run, or use a new numbered name.**
3. What is recorded is **absolute pressure** (Pa); overpressure = value − operating pressure (usually 101325 Pa).

### 6.2 Contours and multi-frame rendering

- Planes: `/display/surface/plane-point-n-normal <name> <px> <py> <pz> <nx> <ny> <nz>` (point + normal). **Vertical vs horizontal is distinguished by the normal**: horizontal `0 1 0`, vertical `0 0 1`.
- **Rebuild the plane after every `read-data`, with a unique name per frame**; building it once for the whole run is unreliable.
- Variable and colour-scale range go through the **interactive** `/display/contour` (variable name first, then min, max). Multi-frame comparisons **must fix min/max**, otherwise colours are not comparable.
- **Call `/display/re-render` before every save**, otherwise from the second frame on `save-picture` captures the previous frame (symptom: "only the mesh, no contour").
- **Do not write** `/display/set/contours/filled-contours yes` / `node-values yes` — they do not accept inline arguments, the default is already yes, and removing them leaves the image byte-identical.
- Before `save-picture`, use `/display/set/picture/x-resolution`, `y-resolution` (these two do accept inline arguments).
- **Render multiple frames serially within one session** (~1 min for 2 frames, ~2 min for 8), do not restart Fluent per frame.

---

## 7 Post-processing and delivery data (P5 in detail)

### 7.1 ⭐ Prefer reading `.h5` offline over starting a Fluent session

`.cas.h5` / `.dat.h5` are standard HDF5. For every "extract numbers and compute metrics" post-processing task (areas, fluxes, extrema, threshold radii, time series, CSVs for downstream), compute offline with `h5py`:

- Time drops from **~30 min for 3 cases** to **~20 s**;
- No license consumption, no commit charge, and **you can produce incremental output for finished frames while the long run is still going**;
- No dependence on lightly-tested interfaces like CFF / iso-clip / `report_definitions`, so **there is no silent failure**;
- Bit-for-bit reproducible; changing one line of the script recomputes every historical frame.

**Three must-check pitfalls** (see `references/offline-h5-postprocessing.md`, `references/offline-cells-and-species.md`):

1. **In 2024R2 the mesh lives in `.cas.h5` and the field in `.dat.h5`** — reading a dat as if it were a mesh raises `KeyError: 'meshes'`; you **must read them as a pair**.
2. **Face-field indexing differs by field**: in the same `.dat.h5`, `SV_VOF` uses global face ids (length = total faces) while `SV_T` uses the boundary-face basis (length = number of boundary faces). Converting them uniformly **silently misaligns** (measured: `∮αdA` came out 0.46025 versus a true 0.421395) ⇒ **decide by array length**, and **align digit-for-digit with the same quantity reported by Fluent in `monitors_<S>.csv`**.
3. **`zoneTopology/name` is a single semicolon-joined string** (`shape=(1,)`), not an array of strings ⇒ `decode().split(";")` first.

Cases that still require a Fluent session: interpolating/resampling with Fluent, extracting iso-surface geometry, defining and evaluating custom field functions. Mixing is fine, but do not shove everything back into Fluent for the sake of uniformity.

When you need 3D voxels/slices but `dat.h5` has no cell centroids and volumes: back-compute them from `c0`/`c1` (use the identity `nface + nint = 4×ncell` to test whether the mesh is pure tetrahedra); the measured deviation of the volume-weighted mean against Fluent's own report is **7.9e-09**.

### 7.2 Four delivery forms (choose by acceptance quantity — do not force one)

| Form | Content | Typical acceptance quantity | How generated |
|---|---|---|---|
| **A Time-series scalar** | Two-column CSV `time_s, metric` | Pool volume, covered area, total released mass | Monitor text → `monitor_to_csv.py` |
| **B Radius + arrival time** | Threshold radius table, wavefront arrival times | Explosion damage boundary, splash fan radius | First-peak fit + inverse threshold solve |
| **C Raster mask long table** | `time, cell, red, yellow` | 2D hazard-zone spreading animation | `.xyz` → rasterize → aggregate |
| **D Polygon vertices** | One vertex per line `x_m, y_m` | Irregular coverage outline | Contour extraction + closing + resampling |

**Cross-tool consistency rests on three things**: units and datum written into the file name or a README in the same directory; all-English CSV paths; and the index definition (e.g. `k = i*NZ + j`) **identical in the raster script, the long-table conversion, and the downstream parser** — change one and you must change all three.

### 7.3 Four rasterization conventions (all learned the hard way)

1. **State the slice-band thickness** (e.g. breathing height `y ∈ [1.5−0.1, 1.5+0.1] m`); omitting it makes the result irreproducible.
2. **Validate area with a per-point argmin nearest neighbour, not `scipy.interpolate.griddata(method="nearest")`** — griddata is Delaunay-hull based and measured 20% low (32.27 vs 40.57 m²).
3. **Never use linear interpolation for a binary mask** — it smears the peak and measured area jumped from 40.6 to 80.9 m². Linear is only appropriate for continuous colour-scale contours.
4. **High-density rasters must be denoised** — when there are far fewer CFD cells than target grid points, nearest-neighbour produces a mosaic (measured: the red zone fragmented into 38 connected components with the largest at 59%). For `NX ≥ 50`, apply `3×3 closing + 3×3 median ×2`: fragments 38 → 7, largest-component share 59% → 84.8%, at the cost of +7% area.

### 7.4 Threshold criteria and fitting

- **Take the incident first peak, not the global maximum.** With a wall outer boundary, shock reflection stacks up a higher spurious peak (measured at 20 m: the global peak 117.1 kPa @ 0.090 s is the reflection, the true incident first peak is 52.6 kPa @ 0.0475 s). Remove it by searching only the first 60% of the time window (`monitor_to_csv.py --window 0.6`).
- **Peak–distance decay fit** `P(r) = a·r^b` by log-log least squares; `b ≈ −1` agrees with a spherical strong shock `P ∝ 1/r` and serves as an order-of-magnitude check.
- **Damage thresholds are an external criterion, not a CFD product.** If a reviewer specifies a standard or a dose–time curve, the radii must be recomputed — **the report must state the threshold source explicitly**.
- **Inverse solve**: `r = exp((ln threshold − ln a) / b)`. **Datums must be aligned** (measurements taken from the component side wall vs. a downstream circle centred on the axis differ by half a component dimension).
- The proper fix is to switch the outer boundary to `pressure-far-field` (gauge 0, Mach 0, T 298 K) and recompute, which physically models an infinite ambient.

---

## 8 Deliverable: the `.wbpj` project (P6 in detail, hard requirement)

**Every case delivery must include a Workbench project entry point.** A pipeline-produced `*.cas.h5` / `*.dat.h5` **is not a finished delivery** — it is an intermediate only you can use. The user must be able to **double-click the `.wbpj`** and inspect settings and results in Fluent / CFD-Post, and change them.

Recipe and all pitfalls: `references/wbpj-project-generation.md`. Five bottom lines:

1. **Multiple frames means one system per frame**, and **the case of frame N must be paired with the data of the same frame**. **Never attach a case without its data** (the Solution stays in an incomplete state and the user double-clicking Results may be prompted to update and accidentally start a solve).
2. **Make the project portable** (copyable to another machine): copy the case/dat into the project `_files` first, then `Import`; the `dat` must carry `ContainerAssociations: ["Solution"]` plus the system property `"Start from available data": "True"`, otherwise the initial field is not used when the user runs it.
3. **`Edit()` always fails under `-B` batch mode** — batch can only **register references**, not actually read a case; the system display name must be set via `DisplayText` (using `DisplayName` makes the journal crash silently).
4. **Both criteria must pass before delivery**:
   - Offline static inspection (Location existence / attached containers / system display names / delivery manifest → glob → actual files on disk);
   - Headless read-back (`RunWB2 -B -R`: `Open` → `GetAllSystems` → per system `Setup/Solution.GetFiles()` non-empty → `GetMessages()==[]`).
5. **Tell the user which entry to use**: the delivery note must say "Update / double-click `Solution`", and you must confirm in the Fluent console that **both the case and the dat were read**. Sending the user to `Setup` shows cold-start initial values and makes them conclude "it isn't configured".

---

## 9 Processes, memory, disk

- **Count instances by the number of `cx2420.exe`** (one per instance), not `fluent.exe` (the launcher has several).
- **Clean up leftovers**: a crash leaves `cx2420.exe` / `fl2420.exe` / `fl_mpi2420.exe` (about 2.7 GB combined). `taskkill fluent.exe` does not kill them; all three must be killed together.
- **Judge memory by commit, not physical availability**: the crash message `ST_Create_Store: out of memory` is a **commit allocation failure**. Measured once: `ullAvailPhys` 3.33 GB (looked insufficient) while `ullAvailPageFile` was **19.97 GB**; released against the commit criterion it ran at full speed with zero paging.
  - Guard condition: `available commit ≥ single-job commit × 1.5`; physical availability is only a soft threshold (≥2.5 GB).
  - Single-job commit references: 404k cells + DO 16 directions + implicit VOF + solidification, `-t4` ≈ **6.1 GB**; 632k ordinary transient `-t6` peaks at ≈ 5.8 GB. On a 16 GB machine such jobs **can only run one at a time, serially**.
- **"Step 1 hangs for hours without emitting Flow time" has twice been confirmed to be insufficient memory**, not divergence.
- **Disk estimate**: `auto_save`'s `case_frequency` defaults to `if-case-is-modified` ⇒ the case is written once (overwritten, ~43 MB) only if it changed before the solve, while data accumulates per frame (~275 MB) ⇒ 12 frames ≈ **3.35 GB**. Do not multiply the case by the frame count.
- Cost magnitudes must be measured: an ordinary transient is about 6.6 s/step (632k, `-t4`); 404k + DO + implicit VOF + solidification measured **36–40 s/step**; 1.63M + implicit VOF + energy measured **64–69 s/step**. **Estimate ETA from the mean of the most recent complete block**, not by extrapolating the first few steps (that reads ~30% high).
- Backflow noise: `Reversed flow on N faces of pressure-outlet X` is a **normal warning**, not evidence of divergence.

---

## 10 Troubleshooting quick table (most frequent)

The full table (six categories: autosave / resume / memory / processes / multiphase / rasterization) is in `references/troubleshooting.md`.

| Symptom | Root cause | Fix |
|---|---|---|
| `License is not available` / `GPGPU computing disabled` / `floating point exception` at launch | Solver GPGPUs per Machine is set to a non-zero value in the Launcher | Set it to **0** |
| Gas does not expand, pressure field unchanged | The high-pressure gas region is fully enclosed by its own wall | Change that wall to `interior` and **write-case immediately** |
| Step 1 pins the CPU but never emits `Flow time` | Insufficient free memory; or a point-surface exists in the solver journal | Clear leftover processes / check commit memory; remove the point-surface |
| Journal stops with `invalid command "xxx"` | The command was deprecated in 24.2 or requires interaction | Check the deprecation table, then verify with a probe |
| Subsequent journal lines get "eaten" | An overwrite confirmation consumed them | Add `ok`; **do not** disable overwrite confirmation (with it off, the same arguments become fatal errors) |
| Resume reports `The mesh has been modified / data incompatible` | A zone-type change altered the mesh, but autosave stores only fields | write-case immediately after the zone change and resume from that case |
| Resume reports `Update_Time_Level: invalid data` | Second-order transient is missing the N−1 time level | Resume from the write-case case plus its matching data |
| Spurious extra peaks in the overpressure curve | Wall outer boundary, shock reflection | Switch the outer boundary to `pressure-far-field`; or take only the first peak and document the exclusion |
| Whole peak shifted by one atmosphere | patch used gauge vs absolute inconsistently | Unify the basis: patch takes gauge pressure, overpressure = absolute − operating pressure |
| VOF interface oscillates / smears | Implicit body force off / second-order upwind for the interface / mesh too coarse | Enable Implicit Body Force, switch to Compressive or Modified HRIC, refine the interface |
| **The run works but the liquid slug hangs in mid-air** | **Phase material assignment failed silently** (`material` is an interactive command; missing `yes` means no error and no effect) ⇒ phase-2 is still air | Use `.../phase-domains/phase-2/material yes slag`; **verify by reading back `phase-2-density` from field data** |
| **patch reports `0 cells marked`** | Register created after / `reg.type` set after `standard_initialize` / `cell_zones` not passed `[]` | The three ordering rules; registers must be **baked into the case** |
| **Patching many registers one by one, only a few take effect** | Per-call `calculate_patch` **does not accumulate** (measured: only 3 of 12 blobs applied, 24% injected) | **Put all registers into a single call**; add a "sacrificial slot" to patch the last one — `cases/S1-foam-slag-splashing.md` |
| **Field data "right values, wrong positions"** | `ScalarFieldDataRequest`'s `node_value` defaults to True (per-node values, misaligned with face centres) | Pass **`node_value=False`** |
| **Offline area / extrema "almost right but not quite"** | Face-field indexing differs by field (see §7.1) | Decide by array length + align digit-for-digit with Fluent's reported value |
| **A delivered metric column is identically zero** | That quantity depends on a Dirichlet fixed-temperature boundary; it is not a computational error | **For any metric that is identically zero, go back and check the BC type it depends on** |
| The long run silently disappears halfway | The process tree was killed with the session or by a reboot | Long runs must be **revived by an external periodic trigger** (Task Scheduler + idempotent PID lock) |
| The computer flashes a black window every 15 min | The scheduled task uses `python.exe` (Subsystem=3) + `InteractiveToken` ⇒ a console is created on the desktop each time | Switch to **`pythonw.exe`** + add a stdout fallback in the entry point (`print()` is **silently dropped** under `pythonw`, not a crash); delete the task when done |
| Task Scheduler "Last Run Result" = `0x800710E0` | The watchdog is blocked waiting on a long run and `IgnoreNew` rejected later triggers ⇒ incremental post-processing hung off it never executes | Use a **blocking supervision loop**: do incremental post-processing while waiting, judge stalls by progress-file mtime, and `taskkill /T /F` |
| `.dat.h5` raises `KeyError: 'meshes'` | The mesh is in `.cas.h5`; the dat top level only has `results/settings` | Post-processing **must read the pair** |
| The "ambient air" in a species case turns into pure nitrogen | `standard_initialize()` fills the difference species `last_species` with 1 | Build the mixture as `{so2, air}` with `air` as the difference species; do not call `copy_by_name('air')` again (yields `air-1`) |
| Post-processing step returns rc=2 and the chain retries forever | The script's positional argument is `nargs="?"`, accepting one case, but several were passed | Change to `nargs="*"` + per-case `try/except`; after wiring it up, **actually run it once** and check rc |
| `OSError: [Errno 22]` raised in `PIL/Image.py` | The target PNG is held by another process (the image preview panel) | Retry and save to `<name>.busy.png`; never raise |
| A case exits with `exit=1` at launch, log ends in `UnicodeEncodeError: 'gbk'` | The log contains characters GBK cannot encode (`ṁ` / `²` / `⇒`); `print` terminates the process under a Chinese Windows locale | Call `sys.stdout.reconfigure(errors="replace")` in the entry point + inject `PYTHONIOENCODING=utf-8` into the chain |

---

## 11 Hard rules

1. **Always probe an unverified TUI command first.** Run a journal containing only that command and read the log. Guessing commands in bulk costs you a journal that stalls mid-way.
2. **Always write-case immediately after changing mesh-related settings (zone types)**, otherwise none of this run's autosaves can be resumed.
3. **Do not write inline `yes`/`no` for menu items that do not accept arguments.** `Overwrite confirmations ... will ignore the following journal` in the log is exactly this bug; **and do not silence it by disabling overwrite confirmation**.
4. **Delivered data must state its basis**: units, datum, threshold source, slice height, time window. Data that cannot be reproduced is not data.
5. **Prove newly written "glue code" before committing to a long run.** A skill can cover known, recurring pitfalls; it cannot cover parsing / flags / launch code you just wrote and are running for the first time. Three one-minute gates:
   - **Test the parser against real file names** (`re.findall(r"\d+", "X_auto-1-00050.dat.h5")` — the last run of digits is the `5` in the extension, so step 600 reads as step 5);
   - **Prove the semantics of a flag before trusting it** (`RESUME=1` actually set `force_restart=True` and restarted from t=0);
   - **Confirm the long-run launcher is alive across tool calls** (an "it's running" observation inside the same call is not evidence).
6. **Every case delivery must include a `.wbpj` project entry point** (§8). A script-produced `cas.h5`/`dat.h5` is not a finished delivery.
7. **Numerical compromises must be labelled.** Lowering the density ratio, turning off surface tension, equivalent fog blobs, sub-grid bases — all acceptable, but **the delivery document must state "this is an engineering assumption"**. Never package it as a physical conclusion.
8. **Check magnitudes against the baseline first.** If results are off the baseline magnitude, report "off". **Do not invent a physical explanation to rationalize it.**
9. **Every addition must be registered.** A new `references/*.md` or `scripts/*.py` must get a row in §12 (resource map) / §4.4 (script inventory); a new case card must pass `scripts/check_cases.py` with zero errors. **A file nobody registered does not exist for the next person.**
10. **Taking over: inventory first, originals read-only, never rebuild** (§0.0). When handed someone else's case, run `scripts/inspect_case.py` to fix the anchor instead of picking a spot and editing; put every change on a copy; change only what evidence proves defective and record the rest as "kept as-is". **"The first half was done by someone else" is not a reason to skip gates — precisely because it never passed your gates, it needs verifying.**

---

## 12 Resource map

**General references `references/`** (written in Simplified Chinese)

| File | Content |
|---|---|
| `tui-commands.md` | All verified commands, interactive answer sequences, deprecated-command table, VOF/species enabling chains, contour and export chains |
| `intake-existing-case.md` | **Taking over someone else's case**: artifact→stage table, the five questions you must answer, an eight-step diagnostic order for "it ran but did not work", six traps, "what you want to change → which stage", originals read-only and "never rebuild" |
| `case-setup-checklist.md` | Panel-by-panel checklist (three branches: compressible transient / VOF / species transport), every item with a "why" |
| `meshing-routes.md` | Meshing route decision tree: Fluent Meshing GUI / scripted gmsh / reuse an existing mesh; the three fake CGNS import crashes; the zone-ID reshuffle trap after re-importing a mesh |
| `troubleshooting.md` | Symptom → root cause → fix (A launch / B physics / C divergence / D segfault / E journal / F processes / G mesh / H rasterization / I PyFluent API / J density-based shock / K external-mesh SIGSEGV / L reports returning `None` / M geometry shrunk 1000× / N non-ASCII path / O mesh-size unit / P `solid` volume region / Q silent non-overwrite / R argument names and value shapes / S offline `.h5` semantics: residuals 1000× too small, `cellType` mistaken for `zoneType`) |
| `auto-resume-and-guard.md` | Long-run launcher, segmented resume, watchdog deployment, encoding traps, Task Scheduler flashing windows and blocking supervision |
| `offline-h5-postprocessing.md` | ⭐ Offline `.h5` reading: structure paths, CSR expansion, face-field basis, `SV_VOF` semantics, degenerate-metric detection, footprint rendering |
| `offline-cells-and-species.md` | ⭐ Offline post-processing (species): mesh/field separation, back-computing centroids and volumes from `c0/c1`, mass → mole fraction, initialization traps, `NaN ≠ 0` |
| `field-export-and-rasterize.md` | Field export → slice → nearest neighbour → threshold → denoise → wide/long table → per-cell verification |
| `footprint-contours.md` | Outline time-series extraction: face → node quantities, closing along the free boundary arc (a reversed direction self-intersects silently), double-threshold filtering, independent shoelace check, fixed-vertex resampling |
| `pyfluent-vof-sputtering.md` | PyFluent API-layer failures: silent phase-material failure, register+patch ordering, 6-rank `wta` crash, `node_value` misalignment, memory budget |
| `wbpj-project-generation.md` | ★ Generating a `.wbpj` that "shows results on double-click": template names, `DisplayText`, `Import` usage, the four-step portability rule, two criteria |

**Case library `cases/`** — see the index in `cases/README.md` and the template `cases/_TEMPLATE.md` (English versions: `cases/README.en.md`, `cases/_TEMPLATE.en.md`); the contribution procedure is §4 there; run `python scripts/check_cases.py` after adding a card.

**Smoke test `tests/smoke/`** — run it first whenever the version or the machine changes: a 3D
rectangular duct in laminar flow judged against an analytical solution, covering the whole chain
(geometry → mesh → fluid zone → zone split → inlet/outlet → boundary conditions → solve → report)
in a few minutes. Two criteria: **continuity ≤2 %** (insensitive to the mesh, catches setup
errors) and **peak-ratio ±10 %** (sensitive to the mesh). Current status and measured numbers
are in `tests/smoke/README.md`.

Three things used to be footnotes you had to memorise — a 1000× geometry shrink, a non-ASCII
path, mesh sizes read in the file's declared unit — and four more sat underneath them. All seven
are now enforced by guards in `tests/smoke/_common.py`, which stop the run and explain the cause
instead of letting Fluent produce a plausible wrong answer. **When you edit the smoke test, do not
route around those guards** — routing around them reinstalls the trap (see `troubleshooting.md`
M–R).

**Scripts `scripts/`** — see §4.4.
