#!/usr/bin/env python3
"""
Deployment Module for Short Gainers Agent

Deploys reports to Netlify automatically.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DeployResult:
    """Result of a deployment."""
    success: bool
    url: Optional[str] = None
    deploy_url: Optional[str] = None
    error: Optional[str] = None


def deploy_to_netlify(
    reports_dir: str = "./reports",
    site_id: Optional[str] = None,
    auth_token: Optional[str] = None,
    production: bool = True,
) -> DeployResult:
    """
    Deploy reports to Netlify.

    Args:
        reports_dir: Directory containing the reports
        site_id: Netlify site ID or name (e.g., "singular-douhua-5443a7")
        auth_token: Netlify auth token (or set NETLIFY_AUTH_TOKEN env var)
        production: Deploy to production (True) or draft (False)

    Returns:
        DeployResult with URL if successful
    """
    reports_path = Path(reports_dir).resolve()

    if not reports_path.exists():
        return DeployResult(
            success=False,
            error=f"Reports directory not found: {reports_path}"
        )

    # Get credentials from env if not provided
    site_id = site_id or os.environ.get("NETLIFY_SITE_ID", "")
    auth_token = auth_token or os.environ.get("NETLIFY_AUTH_TOKEN", "")

    if not site_id:
        return DeployResult(
            success=False,
            error="Netlify site ID not configured. Set NETLIFY_SITE_ID env var or use --netlify-site"
        )

    # Build command using PowerShell on Windows for better compatibility
    if os.name == 'nt':  # Windows
        cmd = [
            "powershell", "-Command",
            f"netlify deploy --dir '{reports_path}' --site {site_id}"
        ]
        if production:
            cmd[2] += " --prod"
        if auth_token:
            cmd[2] += f" --auth {auth_token}"
    else:
        cmd = ["netlify", "deploy", "--dir", str(reports_path), "--site", site_id]
        if production:
            cmd.append("--prod")
        if auth_token:
            cmd.extend(["--auth", auth_token])

    try:
        print(f"Deploying {reports_path} to Netlify...")

        # Run deployment
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=180,
            encoding='utf-8',
            errors='replace',  # Handle encoding issues
        )

        output = result.stdout or ""
        stderr = result.stderr or ""

        # Check for success indicators in output
        if "Deploy is live" in output or "deploy is live" in output.lower():
            # Extract site name from site_id if it's a UUID
            if len(site_id) > 30:  # Looks like a UUID
                # Try to extract URL from output
                for line in output.split("\n"):
                    if "https://" in line and "netlify.app" in line:
                        # Extract URL (might have ANSI codes)
                        import re
                        urls = re.findall(r'https://[a-zA-Z0-9-]+\.netlify\.app', line)
                        if urls:
                            return DeployResult(success=True, url=urls[0])

            return DeployResult(
                success=True,
                url=f"https://kaos-short.netlify.app",  # Fallback to known URL
            )

        if result.returncode != 0:
            error_msg = stderr.strip() or output.strip()
            # Clean ANSI codes from error
            import re
            error_msg = re.sub(r'\x1b\[[0-9;]*m', '', error_msg)
            return DeployResult(
                success=False,
                error=f"Netlify deploy failed: {error_msg[:200]}"
            )

        return DeployResult(
            success=True,
            url=f"https://kaos-short.netlify.app",
        )

    except subprocess.TimeoutExpired:
        return DeployResult(
            success=False,
            error="Netlify deploy timed out"
        )
    except FileNotFoundError:
        return DeployResult(
            success=False,
            error="Netlify CLI not found. Install with: npm install -g netlify-cli"
        )
    except Exception as e:
        return DeployResult(
            success=False,
            error=f"Deploy error: {str(e)}"
        )


def check_netlify_cli() -> bool:
    """Check if Netlify CLI is installed."""
    try:
        result = subprocess.run(
            ["netlify", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def netlify_login() -> bool:
    """
    Open Netlify login in browser.

    Returns:
        True if login command executed
    """
    try:
        subprocess.run(["netlify", "login"], timeout=120)
        return True
    except Exception as e:
        print(f"Netlify login failed: {e}")
        return False
