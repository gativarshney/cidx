# Release runbook

The exact steps to cut a cidx release. Everything automated lives in
`.github/workflows/release.yml` (PyPI trusted publishing — no tokens, no
secrets); this file is the ordered checklist for the manual parts.

## One-time setup (completed 2026-07-30 for 0.1.0a1; kept for reference)

1. **Name check (ADR-001).** Confirm `cidx` is still free on PyPI:
   <https://pypi.org/project/cidx/> should 404. If it is taken, stop and
   decide a new name before anything else.
2. **PyPI trusted publisher.** On <https://pypi.org> (logged in as the
   project owner): *Your account → Publishing → Add a new pending
   publisher*, with exactly:
   - PyPI project name: `cidx`
   - Owner: `gativarshney`
   - Repository name: `cidx`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. **GitHub environment.** In the repo: *Settings → Environments → New
   environment* named `pypi`. (Optionally add yourself as a required
   reviewer so a tag push cannot publish without a click of approval.)

## Every release

1. **Pre-flight.** On a clean, up-to-date `main`:
   - CI is green for the commit you are about to tag.
   - `version` in `pyproject.toml` is the version you are releasing.
   - `CHANGELOG.md` has a dated section for that version and an empty
     `[Unreleased]` above it.
   - `.github/ISSUE_TEMPLATE/bug_report.yml` placeholder shows the new
     version.

2. **Tag and push.** The tag must be `v` + the exact pyproject version:

   ```bash
   git tag v0.1.0a1
   git push origin v0.1.0a1
   ```

3. **Watch the release workflow.** GitHub → Actions → Release. The `build`
   job re-runs lint and the full test suite, builds the wheel and sdist,
   and the `publish` job uploads via trusted publishing. If it fails,
   nothing was published; fix, delete the tag (`git tag -d … && git push
   --delete origin …`), and start over — never re-tag a published version.

4. **Post-publish verification** (fresh terminal, no repo checkout needed):

   ```bash
   uvx cidx --version
   ```

   Then one real end-to-end run against any repository:

   ```bash
   uvx cidx index --repo path/to/some/real/repo
   uvx cidx query <some-known-symbol> --repo path/to/some/real/repo
   uvx cidx check --repo path/to/some/real/repo
   ```

   Expect the version you released, a successful index with plausible
   symbol/ref counts, a correct definition line, and `no drift`.

5. **GitHub release.** *Releases → Draft a new release*, choose the tag,
   title `cidx <version>`, and paste that version's CHANGELOG section as
   the notes. For alphas, tick *Set as a pre-release*.

6. **README follow-up (done with 0.1.0a1).** The Quickstart now shows the
   published install path; nothing further needed for later releases.

## Notes

- Alphas (`0.1.0aN`) are name claims and install paths (ADR-012). Releases
  do not depend on evaluation results of any kind (ADR-013): the project is
  complete and releasable on its engineering merits.
- `pip install build twine` are release-side tools, not project
  dependencies; `twine check dist/*` is an optional extra validation of
  metadata rendering before tagging.
