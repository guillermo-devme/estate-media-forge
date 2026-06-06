---
inclusion: fileMatch
fileMatchPattern: "**/pyproject.toml"
---

<!-- Loads only when a Python dependency manifest is in context (e.g. editing pyproject.toml in
     prompt 01). If you ever add/change deps via another manifest (requirements*.txt, package.json),
     pull this in manually with #dependency-safety — do NOT add a package without these checks. -->

# Dependency & Supply-Chain Safety

Goal: never install a compromised, malicious, typosquatted, or abandoned package.

## Before adding ANY dependency
1. **Confirm the exact name** on the official index (PyPI / npm). Watch for typosquats
   (`reqeusts`, `python-jwt` vs `pyjwt`, scoped vs unscoped). When unsure, verify the canonical
   package and its repo.
2. **Check legitimacy**: real repository, recent maintenance, sane download counts, a license,
   and that it isn't a known-malicious or deprecated package.
3. **Prefer the standard library** or an already-present dependency over a new one. Justify each
   new dependency in the PR.
4. **Pin versions** and commit the lockfile (`uv.lock` / `requirements.txt` with hashes /
   `package-lock.json`). No floating `latest`.

## Audit on every manifest change
- Python: run `pip-audit` (and/or `safety`) against the resolved environment; resolve criticals
  before merge.
- Node: run `npm audit --omit=dev` (or `npm audit`); resolve criticals.
- Do not auto-bump across majors without reading the changelog.

## Install hygiene
- Use `--require-hashes` / lockfile installs in CI-like runs. Avoid `curl | bash` installers.
- Never run post-install scripts from untrusted packages without review.
- Keep Velo dependencies minimal; prefer Node built-ins (`crypto`) and Velo modules over npm
  packages inside the Wix site.

## When a vulnerability is found
- Prefer upgrading to a patched version; if none exists, isolate/replace the dependency or
  document the accepted risk with a mitigation. Never silence the finding.
