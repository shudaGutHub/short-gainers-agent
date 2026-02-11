#!/usr/bin/env python3
"""
Simple Web Server for Short Gainers Reports

Serves the generated HTML reports with a clean interface.
Supports live reload when new reports are generated.

Usage:
    python -m src.web_server
    python -m src.web_server --port 8080
    python -m src.web_server --reports ./my_reports
"""

import argparse
import http.server
import json
import os
import socketserver
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv

load_dotenv()


class ReportHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler for serving reports with enhanced features."""

    def __init__(self, *args, reports_dir: str = "./reports", **kwargs):
        self.reports_dir = Path(reports_dir).resolve()
        super().__init__(*args, directory=str(self.reports_dir), **kwargs)

    def do_GET(self):
        """Handle GET requests with custom routing."""
        path = unquote(self.path)

        # Serve landing page at root if no index.html
        if path == "/" and not (self.reports_dir / "index.html").exists():
            self.send_landing_page()
            return

        # Redirect /admin to index with hash
        if path == "/admin":
            self.send_response(302)
            self.send_header("Location", "/#admin")
            self.end_headers()
            return

        # API endpoint for listing reports
        if path == "/api/reports":
            self.send_reports_list()
            return

        # Default file serving
        super().do_GET()

    def do_POST(self):
        """Handle POST requests for the analysis API."""
        path = unquote(self.path)

        if path == "/api/analyze":
            self._handle_analyze()
        else:
            self.send_response(404)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def _handle_analyze(self):
        """Run analysis on provided tickers and deploy."""
        try:
            # Read and parse request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            tickers_str = data.get("tickers", "")
            changes_str = data.get("changes", "")

            if not tickers_str:
                self._send_json(400, {"success": False, "error": "No tickers provided"})
                return

            # Parse tickers
            ticker_list = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]
            change_list = []
            if changes_str:
                change_list = [float(c.strip()) for c in changes_str.split(",") if c.strip()]

            # Build TickerInput objects
            from .batch_processor import TickerInput
            ticker_inputs = []
            for i, ticker in enumerate(ticker_list):
                change = change_list[i] if i < len(change_list) else None
                ticker_inputs.append(TickerInput(ticker=ticker, change_percent=change))

            # Send immediate response that analysis is starting
            # (run synchronously so the client gets the result)
            import asyncio
            from .batch_processor import run_batch_analysis
            from .deploy import deploy_to_netlify

            reports_dir = str(self.reports_dir)

            # Run analysis
            result = asyncio.run(run_batch_analysis(
                tickers=ticker_inputs,
                output_dir=reports_dir,
                include_financials=True,
                include_news=True,
                verbose=True,
            ))

            # Deploy
            deploy_result = deploy_to_netlify(reports_dir=reports_dir)

            url = deploy_result.url if deploy_result.success else None

            self._send_json(200, {
                "success": True,
                "count": result.get("count", 0),
                "tickers": ticker_list,
                "url": url,
            })

        except json.JSONDecodeError:
            self._send_json(400, {"success": False, "error": "Invalid JSON body"})
        except Exception as e:
            self._send_json(500, {"success": False, "error": str(e)})

    def _send_json(self, status_code: int, data: dict):
        """Send a JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status_code)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_landing_page(self):
        """Send a landing page when no reports exist."""
        html = self._generate_landing_html()
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", len(html))
        self.end_headers()
        self.wfile.write(html.encode())

    def send_reports_list(self):
        """Send JSON list of available reports."""
        reports = []
        if self.reports_dir.exists():
            for f in sorted(self.reports_dir.glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.name != "index.html":
                    stat = f.stat()
                    reports.append({
                        "name": f.stem,
                        "file": f.name,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "size": stat.st_size,
                    })

        response = json.dumps({"reports": reports, "count": len(reports)})
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-Length", len(response))
        self.end_headers()
        self.wfile.write(response.encode())

    def _generate_landing_html(self):
        """Generate landing page HTML."""
        # Get list of report files
        reports = []
        if self.reports_dir.exists():
            for f in sorted(self.reports_dir.glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True):
                reports.append(f.name)

        reports_html = ""
        if reports:
            for report in reports[:20]:
                ticker = report.replace(".html", "")
                reports_html += f'<a href="/{report}" class="report-link">{ticker}</a>\n'
        else:
            reports_html = '<p class="no-reports">No reports generated yet. Run the batch CLI first.</p>'

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Short Gainers Agent - Reports</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%);
            color: #fff;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 40px;
        }}
        .header h1 {{
            font-size: 2.5rem;
            margin-bottom: 10px;
            background: linear-gradient(90deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header p {{
            color: #888;
            font-size: 1.1rem;
        }}
        .card {{
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
        }}
        .card h2 {{
            font-size: 1.3rem;
            margin-bottom: 20px;
            color: #60a5fa;
        }}
        .reports-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
            gap: 10px;
        }}
        .report-link {{
            display: block;
            padding: 15px;
            background: rgba(96, 165, 250, 0.1);
            border: 1px solid rgba(96, 165, 250, 0.3);
            border-radius: 8px;
            color: #60a5fa;
            text-decoration: none;
            text-align: center;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .report-link:hover {{
            background: rgba(96, 165, 250, 0.2);
            border-color: #60a5fa;
            transform: translateY(-2px);
        }}
        .no-reports {{
            color: #666;
            text-align: center;
            padding: 40px;
        }}
        .instructions {{
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid rgba(34, 197, 94, 0.3);
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
        }}
        .instructions h3 {{
            color: #22c55e;
            margin-bottom: 10px;
        }}
        .instructions code {{
            display: block;
            background: rgba(0,0,0,0.3);
            padding: 10px 15px;
            border-radius: 6px;
            margin: 10px 0;
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 0.9rem;
            color: #fbbf24;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            color: #666;
            font-size: 0.85rem;
        }}
        .status {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            background: rgba(34, 197, 94, 0.2);
            color: #22c55e;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Short Gainers Agent</h1>
            <p>Trading Research Dashboard</p>
            <span class="status">Server Running</span>
        </div>

        <div class="card">
            <h2>Available Reports</h2>
            <div class="reports-grid">
                {reports_html}
            </div>
        </div>

        <div class="instructions">
            <h3>Generate New Reports</h3>
            <p>Run the batch CLI to analyze top gainers:</p>
            <code>short-gainers-batch --source nasdaq --max 10</code>
            <p style="margin-top: 15px;">Or analyze specific tickers:</p>
            <code>short-gainers-batch --tickers AAPL,MSFT,NVDA</code>
        </div>

        <div class="footer">
            <p>Reports are saved to: <strong>{self.reports_dir}</strong></p>
            <p style="margin-top: 5px;">Refresh this page after generating new reports.</p>
        </div>
    </div>

    <script>
        // Auto-refresh every 30 seconds to check for new reports
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>'''

    def log_message(self, format, *args):
        """Custom log format."""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def create_handler(reports_dir: str):
    """Create a handler class with the reports directory bound."""
    def handler(*args, **kwargs):
        return ReportHandler(*args, reports_dir=reports_dir, **kwargs)
    return handler


def main():
    parser = argparse.ArgumentParser(
        description="Serve Short Gainers reports via HTTP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.web_server                    # Start on port 8000
  python -m src.web_server --port 3000        # Start on port 3000
  python -m src.web_server --reports ./output # Serve from custom dir
  python -m src.web_server --no-browser       # Don't open browser
"""
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="Port to serve on (default: 8000)"
    )
    parser.add_argument(
        "--reports", "-r",
        type=str,
        default="./reports",
        help="Reports directory (default: ./reports)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Host to bind to (default: localhost)"
    )

    args = parser.parse_args()

    # Ensure reports directory exists
    reports_dir = Path(args.reports).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Create server
    handler = create_handler(str(reports_dir))

    with socketserver.TCPServer((args.host, args.port), handler) as httpd:
        url = f"http://{args.host}:{args.port}"

        print("=" * 50)
        print("Short Gainers Report Server")
        print("=" * 50)
        print(f"Reports directory: {reports_dir}")
        print(f"Server URL: {url}")
        print("")
        print("Press Ctrl+C to stop the server")
        print("=" * 50)

        # Open browser
        if not args.no_browser:
            webbrowser.open(url)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")


if __name__ == "__main__":
    main()
