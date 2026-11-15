# Security

Please report vulnerabilities privately through GitHub's "Report a vulnerability" (Security tab)
rather than in a public issue.

- Secrets live only in `backend/.env`, which Git ignores. The frontend never receives API keys.
- Model checkpoints, DICOM files, ZIP archives and SQLite databases are ignored by Git.
- Automated checks in `.github/workflows/ci.yml`: CodeQL, gitleaks, Bandit, pip-audit, npm audit,
  Trivy and dependency review. Dependabot opens pull requests only for security fixes.
- This is research software. Do not expose it on a public network without TLS, user
  authentication and rate limiting in front of it.
