---
id: X0
name: <case name>
class: vof-free-surface        # compressible-shock | vof-free-surface | species-dispersion | single-phase
status: untested          # verified | partial | untested
last_run: YYYY-MM
keywords: [keyword1, keyword2, keyword3]
reuse_of: ""                   # if derived from another case, put its ID
---

# X0 · <case name>

> **One-line portrait**: <who, triggered by what, which physical process, over seconds/milliseconds>.
> **Status**: <verified / partial / untested>｜**Last run**: <YYYY-MM-DD, Fluent 2024R2>｜**Known limit**: <e.g. "the mesh cannot resolve the liquid slug">

## 1 Model selection

| Item | Value |
|---|---|
| Physics class | |
| Solver | pressure-based / density-based |
| Time | transient (order) / steady |
| Multiphase | VOF implicit / none |
| Turbulence | k-ε Realizable / SST k-ω / laminar |
| Energy | on / off |
| Radiation | none / DO (n directions) |
| Gravity | none / Y = −9.81 (**state the axis**) |
| Time step | |
| Total duration | |
| Mesh size | |
| Cost per step | (state core count and machine memory) |
| Acceptance quantities | |

## 2 Geometry and domain

| Item | Value |
|---|---|
| Domain | X × Y × Z = |
| Axis convention | vertical axis = ? |
| Key components | |
| Leak / release port | position, equivalent diameter, whether the hole is pre-cut |
| Symmetry | half domain / axisymmetric or not |

## 3 Mesh

| Item | Value |
|---|---|
| Route | Fluent Meshing Watertight / gmsh / reuse existing mesh |
| Cell count / type | |
| Critical-region refinement | location, target size |
| Resolution check | feature scale / local cell size = ? cells (< 7 cells is unusable) |
| Known defects | isolated bodies, duplicate vertices, ignored thin shells |

## 4 Materials and phases (or species)

| Phase / species | Density | Viscosity | Other |
|---|---|---|---|
| Primary | | | |
| Secondary | | | |

## 5 Models and solver settings

- Pressure–velocity coupling:
- Gradient:
- Pressure interpolation:
- Momentum:
- Volume fraction / species:
- Relaxation factors:
- Other (implicit body force / surface tension / solidification / reaction):

## 6 Boundary conditions

| zone (ID + name) | Type | Value | Why |
|---|---|---|---|
| | | | |

## 7 Initialization and patching

1. Initialization method and initial values:
2. Which quantities, which zones, which values are patched:
3. **t=0 check** (mandatory): <which quantity, which criterion>

## 8 Advancing strategy

- Time-step sequence (including ramps):
- Total steps / physical duration:
- autosave interval and root_name:
- Estimated disk usage:

## 9 Monitoring and acceptance criteria

| Criterion | Standard / baseline | Source |
|---|---|---|
| | | |

## 10 Post-processing and delivery

- Data extraction: offline h5 / Fluent session
- Output files and column order:
- Basis (datum, slice height, threshold, time window):
- Outlines / rasters (if needed):

## 11 Known pitfalls (specific to this case)

| Symptom | Root cause | Fix |
|---|---|---|
| | | |

## 12 Reproduction entry point

```text
(key journal snippet / script name / command)
```

## 13 Reuse and differences

- **Can be copied verbatim**:
- **Must be changed**:
- **Must not be copied**:
