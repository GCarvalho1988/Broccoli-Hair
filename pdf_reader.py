"""Extracts text from the Portfolio Weekly Report PDF."""
import pdfplumber


def extract_portfolio_text(pdf_path: str) -> str:
    """Return all text from the PDF, truncated to 4000 chars."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)[:4000]
    except Exception as e:
        print(f"PDF read failed: {e}")
        return ""
