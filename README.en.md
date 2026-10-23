# fluent-24r2-case-debug

> English | [简体中文](README.md)

**A general-purpose engineering skill for ANSYS Fluent 2024R2 (v242)**: classify the physics → choose a meshing route → build the case with journals / PyFluent → drive batch runs and resumable long runs from scripts → post-process offline → deliver a double-clickable `.wbpj` project.

Every command, parameter and pitfall here comes from **cases actually run** (Windows + Fluent 2024R2 + PyFluent 0.42.1), not from transcribing the manual. Anything not verified is labelled as such.

## What problem it solves

When you drive Fluent from scripts or the command line, the expensive part is not building the model. It is:

- **The TUI disagrees with the documentation** — commands deprecated, interactive prompts swallowing journal lines, the run stopping on `invalid command`;
- **Silent failures** — phase material not assigned, registers not marked, `node_value` indexing misaligned, initialization filling the ambient with pure nitrogen — none of these report an error;
- **Long runs being interrupted** — the session teardown kills the process tree, autosave cannot resume, monitor CSVs double-count after a resume;
- **Incomplete delivery** — nothing but `cas.h5`/`dat.h5`, which the user cannot open or modify.

This skill turns those pitfalls into a **staged workflow + gate criteria + a case library**.

## Install

```bash
# User level (applies to all projects)
git clone <repo-url> ~/.workbuddy/skills/fluent-24r2-case-debug

# Or project level
git clone <repo-url> <project>/.workbuddy/skills/fluent-24r2-case-debug
```

On Windows the default user-level path is `C:\Users\<user>\.workbuddy\skills\fluent-24r2-case-debug`.

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
fluent-24r2-case-debug/
├── SKILL.md                      # Spec: general methodology + 8-stage workflow + hard rules
├── SKILL.en.md                   # English translation of SKILL.md
├── cases/                        # Case library (search here before you start)
│   ├── README.md / README.en.md  # Index + search / contribution rules
│   ├── _TEMPLATE.md / .en.md     # Uniform card template (§1 selection → §13 reuse)
│   └── <ID>-<short-name>.md      # One card per case
├── references/                   # General references (command tables, checklists, troubleshooting)
└── scripts/                      # Reusable scripts + check_cases.py (case library) / audit_sensitive.py (pre-publication audit)
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

