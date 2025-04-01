import re
import click
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
from datetime import datetime

def parse_date_to_iso(date_str: str | None) -> str | None:
    """
    Convert various date formats to YYYY-mm-dd
    Returns None if parsing fails
    """
    if not date_str:
        return None

    patterns = [
        # ISO format
        ("%Y-%m-%d",),
        # ISO with time
        ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"),
        # "Feb 15, 2025" or "February 15, 2025"
        ("%b %d, %Y", "%B %d, %Y"),
        # US and European formats
        ("%m/%d/%Y", "%d/%m/%Y"),
        # Alternative format
        ("%Y/%m/%d",),
        # "15-Feb-25" or "15-February-2025"
        ("%d-%b-%y", "%d-%B-%Y"),
    ]

    for pattern_group in patterns:
        for pattern in pattern_group:
            try:
                dt = datetime.strptime(date_str.strip(), pattern)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

    # Try to extract just year-month-day if string is messy
    ymd_match = re.search(r"(\d{4})[\/\-](\d{2})[\/\-](\d{2})", date_str)
    if ymd_match:
        return f"{ymd_match.group(1)}-{ymd_match.group(2)}-{ymd_match.group(3)}"

    # Final fallback - look for any 4-digit year
    year_match = re.search(r"(\d{4})", date_str)
    if year_match:
        return year_match.group(1) + "-01-01"

    return None


def extract_date(soup: BeautifulSoup) -> str | None:
    """
    Extract date using multiple fallback methods and standardize format:
    1. Try article:modified_time meta tag
    2. Try article:published_time meta tag
    3. Try <time> element with datetime attribute
    4. Try searching in post-header div with regex
    """
    date_sources = [
        (soup.find("meta", property="article:modified_time"), "content"),
        (soup.find("meta", property="article:published_time"), "content"),
        (soup.find("time", {"datetime": True}), "datetime"),
    ]

    for element, attr in date_sources:
        if element and (date_str := element.get(attr)):
            if iso_date := parse_date_to_iso(date_str):
                return iso_date

    # Fallback to text search in post-header
    post_header = (
        soup.find("div", class_="post-header") or soup.find(class_="article-header")
    )
    if post_header:
        # Try to find a date-like string in the text
        date_patterns = [
            # YYYY-mm-dd
            r"\b\d{4}-\d{2}-\d{2}\b",
            # Month Day, Year
            r"\b[A-Za-z]{3,9} \d{1,2},? \d{4}\b",
            # Day Month Year
            r"\b\d{1,2} [A-Za-z]{3,9} \d{4}\b",
            # Various numeric dates
            r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
        ]

        for pattern in date_patterns:
            match = re.search(pattern, post_header.get_text())
            if match and (iso_date := parse_date_to_iso(match.group())):
                return iso_date

    return None


def extract_metadata_from_url(url: str) -> Dict[str, str] | None:
    """Extract metadata from a given URL"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "lxml")
        
        # Extract og:title
        og_title = soup.find("meta", property="og:title")
        og_title = og_title["content"] if og_title else None
        
        # Extract author
        author = None
        author_meta = (
            soup.find("meta", attrs={"name": "author"})
            or soup.find("meta", property="article:author")
            or soup.find("meta", property="og:author")
        )
        if author_meta:
            author = author_meta.get("content")
        
        # Extract and standardize date
        article_date = extract_date(soup)
        
        return {
            "url": url,
            "og_title": og_title,
            "author": author,
            "article_date": article_date
        }
        
    except Exception as e:
        return {
            "url": url,
            "og_title": None,
            "author": None,
            "article_date": None,
            "error": str(e),
        }


@click.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output file (CSV or JSON)")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format",
)
def main(input_file: str, output: str | None, format: str):
    """Crawl URLs from a text file and extract metadata"""
    urls = [
        line.strip() for line in open(input_file)
        if line.strip() and not line.startswith("#")
    ]
    results = []
    
    with click.progressbar(urls, label="Crawling URLs") as bar:
        results = [extract_metadata_from_url(url) for url in bar]
    
    # Print summary
    success_count = sum(1 for r in results if not r.get("error"))
    click.echo(f"\nProcessed {len(results)} URLs ({success_count} successful)")
    
    # Save output if specified
    if output:
        try:
            if format == "csv":
                import csv
                with open(output, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=results[0].keys())
                    writer.writeheader()
                    writer.writerows(results)
            else:
                import json
                with open(output, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2)
            click.echo(
                f"Results saved to {click.style(output, fg="green")} ({format.upper()})"
            )
        except Exception as e:
            click.echo(click.style(f"Error saving output: {e}", fg="red"))


if __name__ == "__main__":
    main()
