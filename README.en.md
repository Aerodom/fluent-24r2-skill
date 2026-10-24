# fluent-24r2-skill

> English | [简体中文](README.md)

**A general-purpose engineering skill for ANSYS Fluent 2024R2 (v242)**: classify the physics → choose a meshing route → build the case with journals / PyFluent → drive batch runs and resumable long runs from scripts → post-process offline → deliver a double-clickable `.wbpj` project.

Every command, parameter and pitfall here comes from **cases actually run** (Windows + Fluent 2024R2 + PyFluent 0.42.1), not from transcribing the manual. Anything not verified is labelled as such.

## What problem it solves

When you drive Fluent from scripts or the command line, the expensive part is not building the model. It is:

- **The TUI disagrees with the documentation** — commands deprecated, interactive prompts swallowing journal lines, the run stopping on `invalid command`;
- **Silent failures** — phase material not assigned, registers not marked, `node_value` indexing misaligned, initialization filling the ambient with pure nitrogen — none of these report an error;
- **Long runs being interrupted** — the session teardown kills the process tree, autosave cannot resume, monitor CSVs double-count after a resume;
- **Incomplete delivery** — nothing but `cas.h5`/`dat.h5`, which the user cannot open or modify;
- **Taking over someone else's half-finished case** — geometry only / mesh only / boundaries set but
  never run / ran but crashed. Any intermediate state is possible. **Take inventory before editing**;
  do not rebuild from scratch, and do not edit the original in place.

This skill turns those pitfalls into a **staged workflow + gate criteria + a case library**.
Taking over has its own entry point: `scripts/inspect_case.py` reads `.h5` offline and emits a
triage report (no Fluent launch, no licence, a few seconds), telling you which stage to resume from.

## Install

```bash
# User level (applies to all projects)
git clone <repo-url> "<user-level skills dir>/fluent-24r2-skill"

# Or project level
git clone <repo-url> "<project root>/<project-level skills dir>/fluent-24r2-skill"
```

Keep the directory name `fluent-24r2-skill`. Where exactly the loader looks for skills is up to your
agent client (one user-level and one project-level location); restart the session or reload the skill
list after installing.

Once installed, tasks involving journals / PyFluent / post-processing / `.wbpj` / Fluent troubleshooting will match this skill automatically.

## Language / 语言

| Entry | File | Note |
|---|---|---|
| Chinese spec | [`SKILL.md`](SKILL.md) | The active skill file |
| English spec | [`SKILL.en.md`](SKILL.en.md) | Full translation, identical section numbers |
| Chinese README | [`README.md`](README.md) | |
| Case index | [`cases/README.md`](cases/README.md) / [`cases/README.en.md`](cases/README.en.md) | |
| Card template | [`cases/_TEMPLATE.md`](cases/_TEMPLATE.md) / [`cases/_TEMPLATE.en.md`](cases/_TEMPLATE.en.md) | |

The skill loader only ever reads `SKILL.md`, so the sibling translation costs **zero context**. Both spec files are drop-in interchangeable:

```bash
cp SKILL.en.md SKILL.md        # switch the skill to English
```

Individual case cards and the `references/` deep dives are currently written in Simplified Chinese — they are full of verbatim Fluent panel strings and measured log output, where translation would lose information. Contributions of English cards are welcome; the template exists for exactly that.

## Structure

```
fluent-24r2-skill/
├── SKILL.md                      # Spec: general methodology + 8-stage workflow + hard rules
├── SKILL.en.md                   # English translation of SKILL.md
├── cases/                        # Case library (search here before you start)
│   ├── README.md / README.en.md  # Index + search / contribution rules
│   ├── _TEMPLATE.md / .en.md     # Uniform card template (§1 selection → §13 reuse)
│   ├── assets/                   # Journals / long tables referenced by cards (empty by default, no binaries)
│   └── <ID>-<short-name>.md      # One card per case
├── references/                   # General references (commands, checklists, troubleshooting, version bounds)
├── scripts/                      # Reusable scripts + check_cases.py / audit_sensitive.py
├── tests/smoke/                  # Smoke test: minimal case with an analytical answer (run this first on a new version)
├── .github/workflows/            # CI: runs both checks on every push / PR
├── CHANGELOG.md                  # Version history (SemVer)
└── requirements.txt              # Dependencies for the offline scripts (numpy / scipy / h5py)
```

## Use it in three steps

1. **Classify the physics**: compressible transient (A) / high-density-ratio multiphase (B) / species transport (C) / single-phase heat transfer (D). See `SKILL.md` §2.
2. **Search the case library**: the index in `cases/README.md` filtered by class + keyword. **Hit** → follow the card, changing only what its "Reuse and differences" section lists; **no hit** → select models yourself from `SKILL.md` + `references/case-setup-checklist.md`.
3. **Run the 8 stages**: P0 freeze the acceptance basis → P1 mesh → P2 build the case → P3 trial-run self-check → **P4 automated long run** → P5 post-processing → **P6 delivery (including `.wbpj`)** → P7 write the case card back.

Every stage has a gate. **A failed gate means no progress.**

## Case library status

| Class | Cases | Status |
|---|---|---|
| VOF free surface | Molten leakage ×3, acid/alkali leakage | verified / partial |
| Compressible shock | Autoclave pressure explosion | ★ verified end-to-end (incl. reflection-peak removal and power-law fit) |
| VOF finite liquid slug | Tapping splashing, foam-slag splashing | ★ verified (impact-point error 3%; foam slag exposes the mesh resolution limit) |
| Species transport | Toxic gas leakage | ★ verified (incl. the `last_species` initialization trap) |

Cases that have not been run (molten metal into water, runaway reaction, material failure, continuous flue-gas source) each have a card too — **route, prerequisite data needs and "what you must not copy" only**, with no result numbers.

## Adding a case

The library **presupposes no particular number of cases** — add at will. The full procedure (decide whether a card is
warranted → fill §1–§13 → update the index → verify) is in
[`cases/README.en.md` §4](cases/README.en.md#4-how-to-add-a-card-full-procedure). Three bottom lines only:

1. Start with Step 0 of §4 — **do not duplicate cards for isomorphic cases**; point `reuse_of` at the closest one and cover the differences only;
2. Mark unrun items "untested" — **never invent numbers**;
3. Run `python scripts/check_cases.py`; passing means zero errors.

## Before publishing

Everything in this repo uses placeholders (`<PROJ>`, `<CASE_DIR>`, `<OUT_DIR>`, `<venv>`, `%AWP_ROOT242%`) rather than
real local absolute paths. Before adding material or pushing the repo to a public URL, run the audit:

```bash
python scripts/audit_sensitive.py            # ERROR count must be 0
python scripts/audit_sensitive.py --strict   # treat WARN as failure too
```

It flags local absolute paths, home directories, e-mails, IPv4 addresses and organisation names. To also check
client names, project codes and similar terms specific to you, list them in `scripts/audit_terms.local.txt`
(one per line; already excluded by `.gitignore` — **do not commit it**).

## Version & compatibility

| Item | Value |
|---|---|
| Current version | **0.1.0** (see [CHANGELOG.md](CHANGELOG.md)) |
| **Verified** | ANSYS Fluent **2024R2 / v242**, Windows x64; PyFluent 0.42.1 |
| **Not verified** | Any other release. If it works there, that is luck, not a contract |

When you move to another release (2025R1/R2 …): **run `tests/smoke/` first**. It uses a 2D
channel flow to check mesh reading, journal commands, the solver and offline reading in a few
minutes. The six most fragile areas and their probe criteria are in
[`references/version-compatibility.md`](references/version-compatibility.md).

> A card is only marked `verified` on the release it was actually run on. If it runs on another
> release, add a `verified_on:` line — **never edit the old numbers**, that would falsify the run.

## Repo governance

| Mechanism | Location | Purpose |
|---|---|---|
| CI | `.github/workflows/validate.yml` | Runs both scripts on every push / PR; any failure turns the build red |
| Case-library check | `scripts/check_cases.py` | front matter, controlled vocabulary, **index ↔ file ↔ status three-way agreement**, registration closure, links, asset references |
| Pre-publication audit | `scripts/audit_sensitive.py` | Absolute drive paths, user directories, e-mails, IPs, organisation names (`--strict` fails on warnings too) |
| Changelog | `CHANGELOG.md` | One line per card or workflow change |

Local self-check before committing (both must pass):

```bash
python scripts/check_cases.py
python scripts/audit_sensitive.py --strict
```

## Caveats

- Every row of the environment table in `SKILL.md` §1 is a **placeholder** (`%AWP_ROOT242%`, `<venv>`, `<PY38>`, …).
  Replace them with your own values on first use — **never copy them literally** — and re-determine the core/memory limits for your machine.
- Geometry sizes, material properties and thresholds in the cases come from specific engineering projects and are **recipe references only**. Substitute your own design data for a new project.
- `PL` / `PG` in `references/` are **example project codes** (liquid-leak project / gas-leak project) used only to keep track of which case came from which project. They **do not correspond to any real project or client**.

## License

[MIT](LICENSE) © 2026 Yan

Use it, fork it, modify it, ship it inside a commercial project — just keep the copyright notice.

### Disclaimer

- **No affiliation with Ansys, Inc.** ANSYS and Fluent are trademarks of Ansys, Inc. This repository is an independent collection of field notes and scripts. It is not endorsed by, sponsored by, or affiliated with Ansys, Inc.
- **Nothing here is an engineering basis.** Geometry sizes, material properties, acceptance thresholds and result numbers in the cases come from specific engineering projects and are **recipe references only**. Substitute your own design data and verify the results independently; do not use them for design, safety assessment or regulatory submission without your own validation.
- **Provided "AS IS"**, without warranty of any kind, as set out in [LICENSE](LICENSE).

