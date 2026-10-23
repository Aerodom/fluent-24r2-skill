# Case library (cases/)

> English | [简体中文](README.md)

One card per **case that has actually been run**. A card is not a project report — it is **a recipe the next person can follow to reproduce the case**: model selection → settings → boundaries → initialization → advance → acceptance → pitfalls.

The library **does not presuppose any number of cases** — it is a container meant to grow. The entries in the index below are only what currently exists.

> ⚠️ The individual cards are written in **Simplified Chinese** (they contain verbatim Fluent panel strings and measured log output). This index, the template and the workflow spec are available in English. English cards are welcome — use [`_TEMPLATE.en.md`](_TEMPLATE.en.md) and keep the same file naming.

## 1. How to use (mandatory before you start)

1. Find the 1–2 most similar cards in the index below by **`class` + keyword**.
2. Read the card's **§1 Model selection** and **§11 Known pitfalls** — these two decide whether you need to rediscover everything by trial and error.
3. Follow the card, **changing only what §13 "Reuse and differences" lists**; copy the rest.
4. **No hit** → select models yourself from [`../SKILL.md`](../SKILL.en.md) §2 + [`../references/case-setup-checklist.md`](../references/case-setup-checklist.md);
   once it runs, you **must write a new card back** (procedure: §4 of this file).

> Search priority: **isomorphic geometry > same physics class > comparable time scale**.
> Prefer reusing a mesh from "same equipment/geometry but different physics" over forcing a recipe whose physics matches but whose mesh cannot resolve the feature (see the lesson in S1).

## 2. Index

| ID | Name | class | One-line recipe | Mesh size | Status |
|---|---|---|---|---|---|
| [L1](L1-molten-shell-leak.md) | Furnace shell water-jacket breach → molten leakage | `vof-free-surface` | Pressure-based + implicit VOF + solidification + DO radiation; side wall 0–3 m must remain wall | 404k | verified (incl. one misdiagnosis post-mortem) |
| [L2](L2-lance-brick-leak.md) | Oxygen lance brick burnout → molten leakage | `vof-free-surface` | Reuse L1, change only the leak-port position/shape | 404k | partial (run together with L1/L3; same boundary defect) |
| [L3](L3-slag-line-leak.md) | Slag-line burnout → molten leakage | `vof-free-surface` | Reuse L1; interruption/resume verified | 404k | partial (interrupted and resumed; duplicate rows in monitor CSV) |
| [L4](L4-autoclave-acid-leak.md) | Autoclave acid/alkali solution leakage | `vof-free-surface` | Ø30 mm hole, 40 kg/s, ρ=1200, dt 2e-3, gravity along Y | not recorded | verified (end-to-end) |
| [B1](B1-molten-water-explosion.md) | Molten leakage into water → explosion | `compressible-shock` | Two stages: L1 leakage → B2 explosion recipe | not recorded | untested (route only) |
| [B2](B2-autoclave-valve-explosion.md) | Autoclave valve failure → pressure explosion | `compressible-shock` | Density-based + ideal gas + 3.6 MPa gauge patch + dt 5e-4, **gravity off** | not recorded | verified (end-to-end) |
| [B3](B3-runaway-reaction-explosion.md) | In-vessel runaway reaction explosion | `compressible-shock` | B2 + reaction source terms (needs external kinetics data) | not recorded | untested (route only) |
| [B4](B4-vessel-material-failure.md) | Vessel material failure → vessel burst | `compressible-shock` | B2 + failure pressure/temperature criteria; cross-check with TNT equivalence | not recorded | untested (route only) |
| [S1](S1-foam-slag-splashing.md) | Foam-slag splashing | `vof-free-surface` | Implicit VOF + multi-sphere register injection (**sacrificial-slot recipe**); first check whether the mesh can resolve the slug | **1.63M** | verified (physics limited by mesh) |
| [S2](S2-tapping-splashing.md) | Tapping spout splashing | `vof-free-surface` | Finite liquid-slug patch + half-domain symmetry + dt 1e-4 ramp → 5e-4 | 633k | verified (impact-point error 3%) |
| [G1](G1-roof-flue-leak.md) | Roof flue-gas leakage with SO₂/As₂O₃ | `species-dispersion` | Species transport + mass-flow inlet (continuous source) + gravity on for heavy gas | not recorded | untested (route only) |
| [G2](G2-offgas-leak.md) | Off-gas port flue-gas leakage | `species-dispersion` | Same as G1, different source location; As₂O₃ needs DPM / phase separation | not recorded | untested (route only) |
| [G3](G3-autoclave-toxic-gas.md) | Autoclave toxic gas leakage | `species-dispersion` | Mixture `{so2, air}` (**air as the difference species**) + breathing-height slice + threshold raster | 74.8k | verified (end-to-end) |

`class` values: `compressible-shock` / `vof-free-surface` / `species-dispersion` / `single-phase`
(**there is no `single-phase` card yet** — when classification lands there, follow the coverage note in `../SKILL.md` §2 instead of forcing a multiphase recipe onto a single-phase case).
Before adding a value, ask whether it differs from the existing four in its **dominant mechanism**; "one more piece of equipment" is not a new class.

> **Status column**: must start with the controlled word `verified` / `partial` / `untested`, with the human-readable
> nuance in parentheses. The card's front-matter `status` must match — `scripts/check_cases.py` enforces the agreement.
> **`not recorded`** means the card genuinely does not record a mesh size; it is not a to-do. **Do not use it for
> scale estimates** — count the cells from the original case if you need the number.

## 3. Card conventions

### 3.1 File name and ID

`<ID>-<short-english-name>.md`, e.g. `L4-autoclave-acid-leak.md`. The ID is **group prefix + two-digit serial**; serials increase within a group and are never reused.

Prefixes are not fixed — open a new group by physics/equipment family and **register it in the table below** (unregistered = the checker fails):

| Prefix | Meaning | Existing |
|---|---|---|
| `L` | Liquid leak — continuous liquid/molten leakage (VOF free surface) | L1–L4 |
| `B` | Blast — explosion / shock / high-pressure release (compressible transient) | B1–B4 |
| `S` | Splashing — finite liquid slugs, ejecta | S1–S2 |
| `G` | Gas — gas/flue-gas dispersion (species transport) | G1–G3 |

### 3.2 Front matter (7 keys — a missing one fails the checker)

```yaml
id: L4
name: <case name>
class: vof-free-surface
status: verified          # verified | partial | untested
last_run: 2026-09
keywords: [keyword1, keyword2]
reuse_of: ""              # set to another card's ID if derived from it
```

`status` is a **controlled vocabulary** — only these three:

| Token | Chinese | Criterion |
|---|---|---|
| `verified` | 实测跑通 | Ran end-to-end from setup to results; every number in the card is measured |
| `partial` | 部分实测 | Main route ran, but some stages/settings are still inferred, or results are affected by a known defect |
| `untested` | 未实测（路线推定） | Never run; the card carries **route, rationale and prerequisite checks only — no result numbers** |

### 3.3 Content rules

- Every number carries a unit; **unverified items say "untested" or "inferred as isomorphic to X"** — never leave a blank, and never invent one.
- A card's **§11 Known pitfalls** covers only pitfalls specific to that case; generic ones live in `../SKILL.md` §10 and `../references/troubleshooting.md` — do not copy them here.
- For English cards use `_TEMPLATE.en.md`; `status` still takes the same three tokens, and the naming rules are unchanged.

## 4. How to add a card (full procedure)

> The goal is not "writing documentation". It is **making sure the next person does not have to re-run the dead ends you already ran**.

### Step 0 · Decide whether a new card is warranted

| Your situation | What to do |
|---|---|
| Only boundary values/properties changed; geometry and mesh requirement unchanged | **No new card** — add one line "variant: parameter X changed to …" to §6/§13 of the existing card |
| Same physics class, different geometry | New card with `reuse_of` pointing at the closest one; body **covers the differences only** (L2 is written this way) |
| `class` changed (different dominant mechanism) | New card required; `reuse_of` may stay empty |
| Isomorphic geometry but the mesh cannot resolve the feature scale | Still create a card; set `status` honestly and state the resolution limit in §3 and §11 (S1 is the example) |
| Just ran the same case for more steps | No new card — update §9 of the existing one |

### Step 1 · Create the file

```bash
cp cases/_TEMPLATE.md cases/<ID>-<short-name>.md
```

### Step 2 · Fill in the front matter

All 7 keys; `status` from the controlled vocabulary only; `id` must match the file-name prefix.

### Step 3 · Fill §1–§13 — where each section's data comes from

This table is worth more than "fill in every section":

| Section | Data source | Must be measured |
|---|---|---|
| §1 Model selection | Copy the solver/model lines straight out of the journal; per-step cost = `total duration ÷ steps` from `.trn` | yes |
| §2 Geometry and domain | 3D model or drawings; **state which axis is vertical** | yes |
| §3 Mesh | `/mesh/check` output + quality report; "resolution" = feature scale ÷ local cell size (< 7 cells is unusable) | yes |
| §4 Materials and phases | Design data / property handbooks — **cite the source** | no, but cite it |
| §5 Models and solver settings | journal text; copy the relaxation factors and schemes actually used, not the "recommended" ones | yes |
| §6 Boundary conditions | First dump the zone list with `/define/boundary-conditions/list-zones`, then fill ID + type + value + **why** for each | yes |
| §7 Initialization and patching | patch commands and values + the **t=0 check result** (`ΣαV`, total mass in domain…) | yes |
| §8 Advancing strategy | Time-step sequence (incl. ramps), total steps, autosave interval, measured disk usage | yes |
| §9 Monitoring and acceptance criteria | State whether the baseline is **hand-calculated / from literature / measured**, with the formula or page | yes |
| §10 Post-processing and delivery | The five elements: units, datum, threshold source, slice height, time window | yes |
| §11 Known pitfalls | Only pitfalls **newly hit** in this run and absent from the generic tables | — |
| §12 Reproduction entry point | Key journal snippet / script name / full command | yes |
| §13 Reuse and differences | Item-by-item against the `reuse_of` card: copyable / must change / must not copy | — |

If a section cannot be written, write "untested" — **do not fill the gap with guesses**; that is worse than leaving it empty.

### Step 4 · Place the assets

Scripts, long tables and geometry parameters go in `cases/assets/<ID>/`, referenced from the card by **relative path** (e.g. `assets/L4/mesh.jou`).
The checker verifies these references exist, so do not leave assets elsewhere and forget to copy them in.

### Step 5 · Update the index

Add a row to **both `cases/README.md` and `cases/README.en.md`** (the two must match — the checker compares them).
The "one-line recipe" should carry the **1–2 most decisive settings**, not a restatement of the case name.

### Step 6 · Run the checker

```bash
python ../scripts/check_cases.py
```

Passing means zero errors. It verifies: front-matter completeness, legal `status` / `class`, ID matching the file name,
`reuse_of` targets exist, **the index and the files agree in both directions**, and relative links plus `assets/` references exist.

### Step 7 · Human self-check

There is one criterion: **can someone who has never seen this project reproduce the case from this card alone?**

Three supporting questions (if you cannot answer, the card is not finished):

1. Are the mesh sizes and boundary values in the card **copied from the log** or **guessed**?
2. Is the acceptance baseline's source stated, so a reviewer can trace it to a formula or a reference?
3. Of the pitfalls I hit this time, which are absent from the generic tables? Did they make it into §11?
