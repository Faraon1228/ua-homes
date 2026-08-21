#!/usr/bin/env python3
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "deploy.yml"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy_marker = "\n  deploy-netlify:\n"
    require(deploy_marker in workflow, "deploy-netlify job is missing")
    validation_job, deploy_job = workflow.split(deploy_marker, maxsplit=1)

    require(
        "python3 scripts/validate-netlify-admin-config.py" in validation_job,
        "frontend validation must check the canonical root Netlify config",
    )
    require(
        "python3 scripts/validate-deploy-workflow.py" in validation_job,
        "frontend validation must enforce this deployment contract",
    )
    require("actions/upload-artifact@v4" in validation_job, "validated web/ must be uploaded")
    require("include-hidden-files: true" in validation_job, "web/.well-known must be deployed")
    require("needs: validate-frontend" in deploy_job, "deploy must wait for frontend validation")
    require("actions/download-artifact@v4" in deploy_job, "deploy must use validated web/")

    main_only_condition = (
        "if: github.ref == 'refs/heads/main' "
        "&& (github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
    )
    require(main_only_condition in deploy_job, "production deploy must be limited to main")
    require("cancel-in-progress: false" in workflow, "production deploys must not be cancelled")
    require("contents: read" in workflow, "workflow permissions must remain read-only")

    require(
        "NETLIFY_AUTH_TOKEN: ${{ secrets.NETLIFY_AUTH_TOKEN }}" in deploy_job,
        "NETLIFY_AUTH_TOKEN secret is not wired",
    )
    require(
        "NETLIFY_SITE_ID: ${{ secrets.NETLIFY_SITE_ID }}" in deploy_job,
        "NETLIFY_SITE_ID secret is not wired",
    )
    require(
        ': "${NETLIFY_AUTH_TOKEN:?NETLIFY_AUTH_TOKEN is not configured}"' in deploy_job,
        "missing auth token must fail before deployment",
    )
    require(
        ': "${NETLIFY_SITE_ID:?NETLIFY_SITE_ID is not configured}"' in deploy_job,
        "missing site ID must fail before deployment",
    )

    cli_versions = re.findall(r"netlify-cli@([0-9]+\.[0-9]+\.[0-9]+)", deploy_job)
    require(cli_versions == ["27.1.2"], "Netlify CLI must be pinned exactly once")
    for flag in (
        "--prod",
        "--context=production",
        "--no-build",
        "--dir=web",
        '--site="${NETLIFY_SITE_ID}"',
    ):
        require(flag in deploy_job, f"Netlify deploy is missing {flag}")
    require("--auth" not in deploy_job, "auth token must be read from the environment, not argv")
    require("test -f netlify.toml" in deploy_job, "deploy must require the root Netlify config")
    require(
        "working-directory: ${{ github.workspace }}" in deploy_job,
        "Netlify CLI must run beside the canonical root config",
    )

    print("Netlify production deployment is pinned, validated, and main-only.")


if __name__ == "__main__":
    main()
