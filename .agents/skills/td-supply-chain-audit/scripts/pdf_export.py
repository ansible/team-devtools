"""PDF export for supply chain audit HTML report.

Converts the standalone HTML dashboard into a print-optimized PDF.
Requires playwright: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PRINT_CSS = """
@media print {
  :root {
    --bg: #ffffff;
    --surface: #f6f8fa;
    --surface-2: #eef1f5;
    --border: #d0d7de;
    --text: #1f2328;
    --text-muted: #636c76;
    --accent: #0969da;
    --critical: #cf222e;
    --high: #bc4c00;
    --medium: #9a6700;
    --low: #1a7f37;
    --info: #636c76;
  }
  body {
    background: white !important;
    color: #1f2328 !important;
    padding: 0.5cm !important;
    max-width: 100% !important;
    font-size: 9pt !important;
    line-height: 1.4 !important;
  }
  .controls, .filter-btn { display: none !important; }
  .show-more-btn { display: none !important; }
  .finding-item-hidden { display: block !important; }
  .collapsible-body { display: block !important; }
  .collapsible-header .arrow { display: none !important; }
  .collapsible-header { cursor: default !important; }
  .collapsible-header:hover { background: inherit !important; }
  th { cursor: default !important; }
  th .sort-arrow { display: none !important; }
  th:hover { color: inherit !important; }
  .timeline-svg { min-width: unset !important; width: 100% !important; }
  .timeline-container { overflow-x: visible !important; }
  table { font-size: 7.5pt !important; width: 100% !important; table-layout: fixed !important; }
  table th, table td {
    padding: 0.4rem 0.5rem !important;
    word-wrap: break-word !important;
    overflow-wrap: break-word !important;
  }
  #repoSummaryTable { min-width: unset !important; }
  #repoSummaryTable th:first-child, #repoSummaryTable td:first-child { width: 16% !important; }
  #repoSummaryTable th:nth-child(n+2), #repoSummaryTable td:nth-child(n+2) { width: 10.5% !important; }
  div[style*="overflow-x"] { overflow-x: visible !important; }
  h1 { font-size: 16pt !important; }
  h2 { font-size: 13pt !important; page-break-after: avoid; }
  h3 { font-size: 11pt !important; page-break-after: avoid; }
  .summary-grid { grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)) !important; }
  .summary-card .number { font-size: 1.4rem !important; }
  .repo-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)) !important; }
  a { color: var(--accent) !important; }
  a[href]::after { content: none !important; }
  .badge { border: 1px solid currentColor !important; }
  .badge-critical { background: rgba(207, 34, 46, 0.15) !important; color: #cf222e !important; }
  .badge-high { background: rgba(188, 76, 0, 0.15) !important; color: #bc4c00 !important; }
  .badge-medium { background: rgba(154, 103, 0, 0.15) !important; color: #9a6700 !important; }
  .badge-low { background: rgba(26, 127, 55, 0.15) !important; color: #1a7f37 !important; }
  .badge-info { background: rgba(99, 108, 118, 0.15) !important; color: #636c76 !important; }
  .verdict-clean {
    background: rgba(26, 127, 55, 0.08) !important;
    border-color: #1a7f37 !important;
    color: #1a7f37 !important;
  }
  .verdict-issues {
    background: rgba(207, 34, 46, 0.08) !important;
    border-color: #cf222e !important;
    color: #cf222e !important;
  }
  .risk-critical .number { color: #cf222e !important; }
  .risk-high .number { color: #bc4c00 !important; }
  .risk-medium .number { color: #9a6700 !important; }
  .risk-low .number { color: #1a7f37 !important; }
  .risk-info .number { color: #636c76 !important; }
  .light-green { background: #1a7f37 !important; }
  .light-yellow { background: #9a6700 !important; }
  .light-red { background: #cf222e !important; }
  tr:hover { background: inherit !important; }
  .footer { page-break-before: avoid; }
}
"""

JS_EXPAND_ALL = """
() => {
    document.querySelectorAll('.collapsible-header').forEach(h => {
        h.classList.add('open');
        const body = h.nextElementSibling;
        if (body) body.classList.add('open');
    });
}
"""


def _prepare_html_for_print(html_path: Path) -> str:
    """Read HTML and inject print-friendly CSS."""
    return re.sub(
        r"(<div class=\"footer\">)",
        r'<div style="page-break-before: always;"></div>\1',
        html_path.read_text(encoding="utf-8").replace(
            "</style>",
            PRINT_CSS + "\n</style>",
            1,
        ),
        count=0,
    )


def _get_playwright() -> type:
    """Import and return playwright's sync_playwright, or exit with guidance."""
    try:
        from playwright.sync_api import (  # noqa: PLC0415
            sync_playwright,
        )
    except ImportError:
        print(
            "ERROR: playwright not installed.\n  Install with: pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        sys.exit(1)
    return sync_playwright


def export_pdf_playwright(html_path: Path, pdf_path: Path) -> None:
    """Render HTML report to PDF using Playwright (Chromium)."""
    sync_playwright = _get_playwright()
    prepared_html = _prepare_html_for_print(html_path)

    tmp_html = html_path.with_suffix(".print.html")
    tmp_html.write_text(prepared_html, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"file://{tmp_html.resolve()}", wait_until="networkidle")
            page.evaluate(JS_EXPAND_ALL)
            page.wait_for_timeout(500)
            page.pdf(
                path=str(pdf_path),
                format="A4",
                margin={
                    "top": "1.5cm",
                    "bottom": "1.5cm",
                    "left": "1cm",
                    "right": "1cm",
                },
                print_background=True,
                prefer_css_page_size=False,
            )
            browser.close()
    finally:
        tmp_html.unlink(missing_ok=True)


def main() -> None:
    """Entry point for PDF export."""
    parser = argparse.ArgumentParser(description="Export HTML audit report to PDF")
    parser.add_argument(
        "--html",
        default=".supply-chain-audit/report.html",
        help="Path to the generated HTML report",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output PDF path (defaults to same name as HTML with .pdf extension)",
    )
    args = parser.parse_args()

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"ERROR: HTML report not found: {html_path}", file=sys.stderr)
        print("Run report.py first to generate the HTML report.", file=sys.stderr)
        sys.exit(1)

    pdf_path = Path(args.output) if args.output else html_path.with_suffix(".pdf")

    print(f"Exporting PDF from: {html_path}")
    print(f"Output: {pdf_path}")
    export_pdf_playwright(html_path, pdf_path)
    size_kb = pdf_path.stat().st_size / 1024
    print(f"PDF generated: {pdf_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
