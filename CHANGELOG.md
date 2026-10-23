# Changelog

All notable changes to this skill are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [SemVer](https://semver.org/). While the major version is `0`,
the case library and the workflow sections may both change.

---

## [0.1.0] — 2026-10-23

First public release. Everything below is a **snapshot**, not an iteration:
the skill had been developed as a private working set and was restructured
into a general workflow + a case library for publication.

### Added

- `SKILL.md` — general workflow: 3-step entry, physics classification (A/B/C/D),
  **8-stage pipeline P0–P7 with pass/fail gates**, automation patterns,
  post-processing, `.wbpj` delivery, hard rules.
- `SKILL.en.md` — full English translation of the above (§0–§12 aligned 1:1).
- `cases/` — case library: index + card template + case cards
  (`L1–L4` leakage, `B1–B4` explosion, `S1–S2` splashing, `G1–G3` gas dispersion).
  Each card carries `class` / `status` metadata and a `reuse_of` pointer.
- `cases/README.md` — how to search, how to decide whether a new card is
  warranted, where every section's data comes from, ID prefix registry.
- `references/` — 12 topic documents (TUI commands, panel checklist, meshing
  routes, troubleshooting, resume/watchdog, offline `.h5` readers, field export
  and rasterization, footprint contours, PyFluent pitfalls, `.wbpj` generation).
- `scripts/` — reusable tooling: `run_fluent_journal`, `auto_resume`,
  `monitor_to_csv`, `export_field_journal`, `make_render_journal`,
  `rasterize_field_to_grid`, plus two checks: `check_cases`, `audit_sensitive`.
- `scripts/check_cases.py` — machine check for the case library: front matter,
  controlled vocabulary, index ↔ file agreement in both directions,
  index status vs front-matter status, reference/script registration,
  relative links, `assets/` references.
- `scripts/audit_sensitive.py` — pre-publication audit: absolute drive paths,
  hardcoded user directories, e-mail addresses, IPv4 literals, organisation
  names, plus an optional local word list (`audit_terms.local.txt`, gitignored).
- `.github/workflows/validate.yml` — CI: both checks run on every push and PR.
- `requirements.txt` — numpy / scipy / h5py for the offline scripts.
- `tests/smoke/` — smoke test whose pass criterion is **analytical** (rectangular-duct
  laminar flow, `u_max/U_mean` from the Fourier series), so it needs no historical
  measurement. **Verified end to end on this machine**: geometry → mesh → solve →
  report, with two criteria (continuity 0.07 %, shape −5.9 %). It is also what
  uncovered the seven problems listed under "Discovered during the smoke test".
- `tests/smoke/_common.py` — shared guards for the smoke test. Every function in it
  exists because a specific failure actually happened; the mapping is a table in
  `tests/smoke/README.md` and each guard is cross-referenced from
  `troubleshooting.md`. Kept standard-library-only on purpose, so a path or unit
  problem is caught *before* Fluent spends a minute starting up.
- `references/version-compatibility.md` — what is actually verified
  (2024R2 / v242) and what must be re-tested on any other release.
- `LICENSE` — MIT, © 2026 Yan. Plus a disclaimer in both READMEs:
  not affiliated with Ansys, Inc.; case numbers are recipe references only.

### Changed

- The skill is named **`fluent-24r2-skill`**: directory name, `name:` in both
  `SKILL.md` / `SKILL.en.md` front matter, and every path in the READMEs. The old name
  carried `case-debug`, which described the original private working set rather than what
  this now is. Installing under the old name keeps working, but the two will not merge.
- Renamed one reference file to a tool-neutral name (`footprint-contours.md`), and
  removed the name of the downstream consumer product from the whole repository.
- `status` in case-card front matter is now a **controlled vocabulary**
  (`verified` / `partial` / `untested`) instead of free text. The human-readable
  nuance stays in each card's `> **状态**` line; the mapping is in
  `cases/README.md` §3.2.
- All machine-specific paths replaced with placeholders
  (`%AWP_ROOT242%`, `<venv>`, `<PY38>`, `<PROJ>`, `<CASE_DIR>`, `<OUT_DIR>`),
  documented in `SKILL.md` §1.
- Project-internal identifiers replaced with the neutral codes `PL` / `PG`.

### Removed

- `references/scenario-method-matrix.md` — superseded by the case library;
  keeping both led to two conflicting sets of numbers.
- One-off patch scripts and a `scripts/archive/` directory that contained a
  hardcoded user path.

### Fixed

- `case-setup-checklist.md` claimed a Ø150 mm liquid slug needs a 0.02 m mesh.
  Measured: **0.012 m (≈9.8 cells across) works, 0.020 m (7.5 cells) shatters
  the slug**. The checklist now states the measured values.
- Trajectory hand-calculation landing point unified to the 2.84 m convention
  (CFD 2.93 m, 3 % error), replacing an earlier 2.7 m figure.
- `SG`/`s1` reference document was missing from the `SKILL.md` §12 resource map
  (a file nobody registers is a file nobody finds).
- `meshing-routes.md` §3 advertised the gmsh scripting route without a warning.
  It now carries a measured caveat: on this machine a gmsh-written `.msh` crashes the
  reader (see `troubleshooting.md` K) and the working path is gmsh → STEP → Fluent
  Meshing → native `.msh.h5`.

### Guards — the seven pitfalls are now enforced by code, not by prose

Documenting a trap is not the same as preventing it. Each row below was a real failure
during the smoke test; each is now a function that fails loudly and says why.

| Pitfall | Guard | Where it fires |
|---|---|---|
| gmsh writes STEP in millimetres with unscaled coordinates (geometry 1000× too small) | `step_unit()` / `step_extent()` read the file back and compute the physical extent | `make_geometry.py` asserts <1 % deviation; `make_mesh.py` reuses the same reading |
| non-ASCII working directory breaks the CAD importer | `require_ascii()` | all four scripts, **before** Fluent starts |
| mesh sizes are interpreted in the file's declared unit | `size_in_file_unit()` converts from physical metres | `make_mesh.py`, before handing sizes to Meshing |
| volume region is created as `solid` | `force_fluid_cell_zones()` converts **and re-reads** to confirm | `run_case.py`, right after `read_case` |
| `m.tui.file.*` unavailable in 0.42.1, while `write_mesh` only exists there in a meshing session | `call_file()` probes `settings.file` and `tui.file` and tries both call forms | every file write |
| argument names and value shapes (`new_type`, `report_of`, `velocity` as an option object) | `set_inlet_velocity()` writes, reads the state back and compares | `run_case.py`, when setting the inlet |
| `write_mesh` / `write_case_data` silently decline to overwrite | `fresh_write()` deletes first, then checks exists / non-empty / **mtime actually moved**; `check_mesh_not_stale()` refuses to solve on a mesh older than the geometry | every file write; before solving |

### Discovered during the smoke test (documented; anything a script can check is now guarded)

- **External mesh readers segfault.** `read-case` on a gmsh 2.2 mesh (quads *and*
  triangles) or on CGNS dies with `SIGSEGV` right after `Building... mesh`, while the
  native `.msh.h5` from Fluent Meshing reads fine. Six controlled experiments rule out
  format, path encoding, core count and PATH propagation. See `troubleshooting.md` K.
- **Fluent Meshing watertight rejects faceted geometry**: STL/TGF/FMD are refused, a CAD
  face (STEP) is required.
- **`describe_geometry.capping_required` is case-sensitive** — `"No"`, not `"no"`.
- **All CAD faces collapse into a single zone** on import; `sep_face_zone_angle` splits
  them back apart.
- **PyFluent 0.42.1 `session.tui.*` calls return `None`** and only print a hint, so any
  automation that branches on a report value silently gets `None`. `m.tui.file.*` is
  worse: it raises `eval: unbound variable / Error Object: file`. Use `m.settings.file.*`
  and read values out of the transcript file. See `troubleshooting.md` L.
- **gmsh declares STEP in millimetres but writes model coordinates unscaled**, so a 1 m
  box arrives as 1 mm and the physics silently shifts three orders of magnitude. Fixed
  by `Geometry.OCCTargetUnit = "M"` plus a read-back unit self-check. See
  `troubleshooting.md` M.
- **A non-ASCII working directory breaks the Meshing CAD importer** with a message that
  blames the file format ("check to make sure the CAD Readers are properly configured"),
  not the path. See `troubleshooting.md` N.
- **Meshing interprets mesh sizes in the file's declared unit, not in metres**:
  `min_size=0.0015` on a millimetre-declared STEP becomes 1.5 µm and the mesher dies
  with `Error: Out of Memory` (then hangs). `import_geometry.length_unit` does not
  override the declaration. See `troubleshooting.md` O.
- **The volume region comes out as `solid`**, so any flow boundary next to it triggers
  "Flow boundary zone found adjacent to solid zone". Convert it to `fluid` before
  setting boundary conditions. See `troubleshooting.md` P.
- **`write_mesh` silently declines to overwrite an existing file.** No exception, no
  message; `os.path.exists()` stays true (stale file), so the next solve silently runs
  on the previous mesh. Delete the target and verify the mtime. See
  `troubleshooting.md` Q.

### Known limitations

- Only **2024R2 / v242 on Windows** is verified. See
  `references/version-compatibility.md`.
- **The smoke test passes, but with a ±10 % band, not ±3 %.** Continuity closes to 0.07 %,
  which is what actually certifies the setup; the peak-velocity ratio reaches 1.622
  against the analytic 1.724 (−5.9 %) on a 531 k-cell polyhedral mesh. A 135 k-cell mesh
  gives −11.2 % and is correctly rejected. Reaching ±3 % needs roughly 1.0 mm sizing
  (≈2.6 M cells), which is beyond a smoke test's budget. `tests/smoke/README.md` carries
  the measured convergence table.
- The smoke test needs a **pure-ASCII working directory**; a Chinese user path is enough
  to break the Meshing CAD import. The scripts fall back to the system temp directory and
  say so, but a CI runner under such a path must set `WORK` explicitly.
- 5 of the cards are `untested` (route only). They intentionally contain **no
  result numbers**; treat them as planning checklists, not as recipes with
  known-good output.
- The case library has **no `single-phase` card** yet; `SKILL.md` §2 states this
  explicitly rather than leaving the gap implicit.
- Entry documents are bilingual (zh + en); case cards and `references/` are
  Chinese only. See `README.md` § Language.
