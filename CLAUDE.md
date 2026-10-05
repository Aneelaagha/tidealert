# TideAlert: working rules

## Workflow rules (standing)
- **Never commit to master.** Every unit of work gets its own branch and PR,
  and the project owner merges it.
- **Plan first for anything large or uncertain.** Report the plan and wait for
  the go-ahead before building. Routine steps inside an approved plan proceed
  without check-ins.
- **No fabricated data.** Unknown stays "unknown" or "not assessed". Never
  interpolate, guess or fill a gap and present it as measured.
- **Hard gates are gates.** If a fix must land before results can be claimed
  (for example the Swannanoa gap-fill), no results from that source are run,
  looked at or reported until the fix is merged and verified.
- **Any change that could alter Harvey's output needs its own review.** The
  161 non-mixed Case fingerprints must stay identical unless the owner
  approves otherwise.
- **State limitations in plain words:** sample size, lower-confidence
  drivers, and what a test does not prove.
- **Reports to the owner** cover what was built, what was verified, what was
  not exercised, the check bar, and the decisions needed.

## Check bar (before every PR)
- pyflakes clean on `scripts/`, `backend/app/services`, `backend/app/routes`,
  `backend/app/main.py`, `notebooks/` and `tests/`. Models are excluded,
  because of their string forward references.
- `alembic check` clean; new migrations round-tripped (downgrade, then
  upgrade).
- Harvey replay (`scripts/run_case_matcher.py 08074500 08076000 08075770`)
  gives 49 / 92 / 11 Cases.
- All 161 non-mixed Case fingerprints identical after rerunning the silence
  sweep and `scripts/listening_demo.py`. The mixed run is excluded; rebuild it
  with `scripts/mixed_harvey_scenario.py`.
- `pytest` and the frontend's `npm run lint` and `npx vitest run` pass, and
  `npm run build` succeeds.
- UI changes are checked in a browser against Harvey and both scenarios
  (and the mixed run where relevant).

## Decisions already made (Week 7)
- **Helene, French Broad:** the study area is clipped to Asheville city
  limits minus the Swannanoa basin (`app.services.study_area`). Tiling the
  3DEP download for the full basin is documented future work.
- **Helene, the gap-fill fix:** discharge interpolation is capped at
  **3 hours**. The cap is documented as informed by Harvey's widest bridged
  gap (150 min), not as a universal constant. A missing step stays missing
  through the river driver, the isolation engine and the case matcher.
- **Missing rainfall:** when the source doesn't cover the window, the
  pipeline says so and skips the rainfall summary and the rain-driver
  evaluation. NOAA AORC v1.1 is documented future work.
- **Ground truth for Helene:** NFIP only, reported as counts, never rates.
- **No synthetic households for real events:** the silence and listening
  engines don't apply to Helene.
- **The donation needs board** is deferred past Week 7.
