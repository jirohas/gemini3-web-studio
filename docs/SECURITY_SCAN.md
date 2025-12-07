# Security Scan Report

2025-02-03 security review after history rewrite. The previous branch lost common history, so this fresh scan verifies that no sensitive secrets remain in the repository.

## Checks performed
- Searched the working tree for common secret patterns (API keys, private keys, hard-coded passwords). Commands used:
  - `rg -n "(AKIA|AIza|sk-[a-zA-Z0-9]{10}|-----BEGIN PRIVATE KEY-----|password\\s*=|secret\\s*=)"` – no matches other than the password input prompt in the UI.
- Confirmed no residual session/usage JSON files are tracked in the repository root.
- Reviewed authentication flow in `app.py` to ensure APP_PASSWORD is mandatory and URL token login is disabled unless SECRET_TOKEN is set.
- Tightened the ignore list to block accidental commits of private keys or local credential bundles.

## Findings
- **No hard-coded credentials detected.** Authentication relies on environment variables or Streamlit secrets.
- **Local auth required.** The app stops execution when `APP_PASSWORD` is missing, preventing default/blank credentials.
- **URL token opt-in.** Token-based auth only activates when `SECRET_TOKEN` is explicitly provided.
- **Session data excluded.** Usage and chat history files remain ignored to avoid leaking user data.

## Recommendations
- Keep `APP_PASSWORD` strong and unique per deployment.
- Store cloud credentials only in environment variables or `st.secrets`; never commit them.
- Rotate `SECRET_TOKEN` and `APP_PASSWORD` if shared or exposed.
- Re-run the ripgrep check above before publishing new branches.
