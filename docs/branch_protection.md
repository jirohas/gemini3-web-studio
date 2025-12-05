# Main branch protection quick steps

You are seeing the GitHub reminder "Your main branch isn't protected". Protecting `main` helps prevent accidental force-pushes or direct commits without review.

## Enable branch protection (GitHub UI)
1. Open the repository on GitHub and go to **Settings → Branches**.
2. Under **Branch protection rules**, click **Add branch protection rule**.
3. In **Branch name pattern**, type `main`.
4. Turn on at least these settings:
   - **Require a pull request before merging** (optionally require 1+ approvals).
   - **Require status checks to pass before merging** (pick your CI jobs).
   - **Restrict who can push to matching branches** (prevents direct pushes; PRs still work).
   - **Do not allow bypassing the above settings**.
   - **Block force pushes** and **Block deletions**.
5. Save the rule.

## If using the ChatGPT Codex Connector
- Keep working on feature branches (e.g., `work`) and open PRs into `main`.
- The connector can still create PRs, reviews, and fix commits on branches that target `main`.
- If pushes to `main` are restricted, ensure the connector account is allowed to push to feature branches and open PRs (it will not need to push directly to `main`).

## API/CLI option (GitHub CLI example)
If you prefer automation, you can create the rule with the GitHub CLI (requires repo admin rights):

```bash
gh api \
  -X POST \
  -H "Accept: application/vnd.github+json" \
  /repos/<owner>/<repo>/rules/branches \
  -f name="main" \
  -f rules='[
    {"type":"deletion","parameters":{"block_deletions":true}},
    {"type":"force_push","parameters":{"block_force_pushes":true}},
    {"type":"pull_request","parameters":{"dismiss_stale_reviews_on_push":false,"require_code_owner_review":false,"required_approving_review_count":1}},
    {"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":true,"required_status_checks":["ci"]}}
  ]'
```
Replace `<owner>/<repo>` and required status checks (e.g., `ci`) with your actual values.
