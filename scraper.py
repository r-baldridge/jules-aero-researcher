import requests
import json
import os
from datetime import datetime, timedelta
import io
import pypdf
import feedparser
import re
import argparse

def download_pdf(url, title):
    """
    Downloads the PDF file to the 'downloads' directory.
    """
    if not url or not url.lower().endswith(".pdf"):
        # Some OpenAlex/NASA URLs might not end in .pdf but return PDF content.
        # We'll try anyway if it's a direct link, but relying on extension is safer for filenames.
        # Let's trust the source logic passed a PDF URL if possible.
        pass

    try:
        if not os.path.exists("downloads"):
            os.makedirs("downloads")

        # Sanitize filename
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
        safe_title = safe_title.replace(" ", "_")[:50] # Limit length
        filename = f"downloads/{safe_title}.pdf"

        if os.path.exists(filename):
            print(f"File already exists: {filename}")
            return

        print(f"Downloading PDF: {title[:30]}...")
        headers = {
            "User-Agent": "AerospaceScraper/1.0 (contact@example.com)"
        }
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()

        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Saved to {filename}")

    except Exception as e:
        print(f"Failed to download PDF for {title}: {e}")

def fetch_arxiv_data():
    """
    Fetches data from arXiv API.
    """
    print("Fetching arXiv data...")
    # Categories: physics.flu-dyn (Fluid Dynamics), cs.RO (Robotics), eess.SY (Systems)
    # Keywords: structural analysis, fitting factors, composite fatigue
    base_url = "http://export.arxiv.org/api/query"

    # Constructing the query
    # (cat:physics.flu-dyn OR cat:cs.RO OR cat:eess.SY) AND (all:"structural analysis" OR all:"fitting factors" OR all:"composite fatigue")
    search_query = '(cat:physics.flu-dyn OR cat:cs.RO OR cat:eess.SY) AND (all:"structural analysis" OR all:"fitting factors" OR all:"composite fatigue")'

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": 20,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }

    # arXiv API requires standard User-Agent or it might block/fail.
    # Also, it redirects http to https, but feedparser handles that if we use requests.
    # However, complex query strings can sometimes be finicky with requests encoding.
    # We will try strict encoding.

    # arXiv can be strict about User-Agent, and sometimes rate limits "python-requests"
    # We use a standard Mozilla UA to avoid immediate 429 in some environments if custom UA is flagged.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        # Note: In a real scenario, if 429 persists, we should implement backoff.
        # But for this initialization script, we'll try once with headers.
        response = requests.get(base_url, params=params, headers=headers)
        if response.status_code == 429:
             print("arXiv API rate limit exceeded (429). Skipping arXiv source.")
             return []
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"Error fetching arXiv data: {e}")
        return []

    results = []
    start_date = datetime.now() - timedelta(days=7)

    for entry in feed.entries:
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            published_dt = datetime(*published_parsed[:6])
            if published_dt < start_date:
                continue

        title = entry.get("title", "No Title").replace('\n', ' ')
        abstract = entry.get("summary", "")
        pdf_url = None

        for link in entry.get("links", []):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href")
                break

        # Fallback to arxiv.org/pdf/ID if not found in links but ID exists
        if not pdf_url and "id" in entry:
             arxiv_id = entry.id.split('/')[-1]
             pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        results.append({
            "title": title,
            "url": pdf_url or entry.get("link"),
            "abstract": abstract,
            "source": "arXiv",
            "relevance": "structural analysis, fitting factors, composite fatigue (arXiv)"
        })

    print(f"Found {len(results)} items from arXiv.")
    return results

def fetch_nasa_data():
    """
    Fetches data from NASA NTRS API for the last 7 days.
    """
    print("Fetching NASA NTRS data...")
    url = "https://ntrs.nasa.gov/api/citations/search"
    start_date = datetime.now() - timedelta(days=7)
    params = {
        "q": "structural analysis fitting factors composite fatigue",
        "published.gte": start_date.strftime("%Y-%m-%d"),
        "page.size": 25  # Limit to avoid too many results
    }

    headers = {
        "User-Agent": "AerospaceScraper/1.0 (contact@example.com)"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching NASA data: {e}")
        return []

    results = []
    for item in data.get("results", []):
        # Double check date in python as backup
        # Try to find a publication date
        pub_date_str = None
        if "publications" in item and item["publications"]:
            for pub in item["publications"]:
                if "publicationDate" in pub:
                    pub_date_str = pub["publicationDate"]
                    break

        # If no publication date, check distributionDate or submittedDate
        if not pub_date_str:
            pub_date_str = item.get("distributionDate") or item.get("submittedDate")

        if pub_date_str:
            try:
                # Format is often ISO 8601 like 2013-08-10T00:01:00.0000000+00:00
                # We handle simple iso format
                pub_date = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00').split('.')[0])
                # Note: Python < 3.11 fromisoformat might be picky about TZ
                # For safety, just comparing string prefix YYYY-MM-DD might be safer if formats vary,
                # but datetime comparison is better.
                # Let's trust the API filter mostly, but this is a backup.
                if pub_date < start_date:
                    continue
            except ValueError:
                pass # If date parsing fails, we rely on API filter

        title = item.get("title", "No Title")
        abstract = item.get("abstract", "")

        # Find PDF link
        pdf_url = None
        if "downloads" in item:
            for download in item["downloads"]:
                if download.get("mimetype") == "application/pdf":
                    links = download.get("links", {})
                    if "pdf" in links:
                        pdf_url = links["pdf"]
                    elif "original" in links:
                        pdf_url = links["original"]
                    break

        if pdf_url and not pdf_url.startswith("http"):
             pdf_url = f"https://ntrs.nasa.gov{pdf_url}"

        if not pdf_url:
            # Fallback to landing page if no PDF
            pdf_url = f"https://ntrs.nasa.gov/citations/{item.get('id')}"

        results.append({
            "title": title,
            "url": pdf_url,
            "abstract": abstract,
            "source": "NASA",
            "relevance": "structural analysis, fitting factors, composite fatigue"
        })

    print(f"Found {len(results)} items from NASA.")
    return results

def fetch_openalex_data():
    """
    Fetches data from OpenAlex API for Aerospace Engineering (Concept ID: C146978453).
    """
    print("Fetching OpenAlex data...")
    url = "https://api.openalex.org/works"

    current_year = datetime.now().year

    # Concept C146978453 is Aerospace engineering
    # Filter by concept and current year to keep it fresh
    params = {
        "filter": f"concepts.id:C146978453,publication_year:{current_year}",
        "per-page": 20,
        "sort": "publication_date:desc"
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching OpenAlex data: {e}")
        return []

    results = []
    # OpenAlex returns publication_date like "2024-07-23"
    start_date = datetime.now() - timedelta(days=7)

    for item in data.get("results", []):
        pub_date_str = item.get("publication_date")
        if pub_date_str:
            try:
                pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d")
                if pub_date < start_date:
                    continue
            except ValueError:
                pass

        title = item.get("display_name") or item.get("title", "No Title")
        # OpenAlex uses inverted index for abstract, which is complex to reconstruct.
        # We'll use the title or check if 'abstract_inverted_index' exists and try a simple reconstruction if needed,
        # but often it's null. We can leave abstract empty or use title.
        abstract = ""

        pdf_url = None
        # Check primary location
        primary_loc = item.get("primary_location", {}) or {}
        if primary_loc.get("pdf_url"):
            pdf_url = primary_loc.get("pdf_url")

        # Check best_oa_location if primary fails
        if not pdf_url:
            best_oa = item.get("best_oa_location", {}) or {}
            if best_oa.get("pdf_url"):
                pdf_url = best_oa.get("pdf_url")

        landing_page = item.get("id") # The OpenAlex ID is a URL

        results.append({
            "title": title,
            "url": pdf_url or landing_page,
            "abstract": abstract, # Often empty for OpenAlex free tier/structure
            "source": "OpenAlex",
            "relevance": "Aerospace Engineering (OpenAlex)"
        })

    print(f"Found {len(results)} items from OpenAlex.")
    return results

def fetch_faa_data():
    """
    Fetches data from Federal Register API for FAA Airworthiness Directives.
    """
    print("Fetching FAA Federal Register data...")
    url = "https://www.federalregister.gov/api/v1/documents.json"
    params = {
        "conditions[agencies][]": "federal-aviation-administration",
        "conditions[type][]": ["RULE", "PRORULE"],
        "conditions[term]": "Airworthiness Directives",
        "order": "newest"
    }

    headers = {
        "User-Agent": "AerospaceScraper/1.0 (contact@example.com)"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching FAA data: {e}")
        return []

    results = []
    for item in data.get("results", []):
        title = item.get("title", "No Title")
        abstract = item.get("abstract") or item.get("description", "")
        pdf_url = item.get("pdf_url")
        html_url = item.get("html_url")

        url_to_use = pdf_url if pdf_url else html_url

        results.append({
            "title": title,
            "url": url_to_use,
            "abstract": abstract,
            "source": "FAA",
            "relevance": "Airworthiness Directives"
        })

    print(f"Found {len(results)} items from FAA.")
    return results

def fetch_brave_data(query, api_key):
    """
    Fetches data from Brave Search API.
    """
    print(f"Fetching Brave Search data for query: {query}")
    url = "https://api.search.brave.com/res/v1/web/search"
    params = {
        "q": query
    }
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 403:
            print("Error fetching Brave data: Invalid API Key")
            return []
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching Brave data: {e}")
        return []

    results = []
    # Brave response structure: data['web']['results'] -> list of items
    web_results = data.get("web", {}).get("results", [])

    for item in web_results:
        title = item.get("title", "No Title")
        url = item.get("url")
        description = item.get("description", "")

        if not url:
            continue

        results.append({
            "title": title,
            "url": url,
            "abstract": description,
            "source": "Brave Search",
            "relevance": query
        })

    print(f"Found {len(results)} items from Brave Search.")
    return results

def load_seen_ids():
    """
    Loads seen IDs from seen_ids.json.
    """
    if os.path.exists("seen_ids.json"):
        try:
            with open("seen_ids.json", "r") as f:
                return set(json.load(f))
        except json.JSONDecodeError:
            return set()
    return set()

def save_seen_ids(seen_ids):
    """
    Saves seen IDs to seen_ids.json.
    """
    with open("seen_ids.json", "w") as f:
        json.dump(list(seen_ids), f, indent=2)

def verify_pdf_readability(url):
    """
    Downloads the first few bytes of a PDF to check if it contains readable text.
    Extracts text from the first page.
    """
    print(f"Verifying PDF readability for: {url}")
    headers = {
        "User-Agent": "AerospaceScraper/1.0 (contact@example.com)"
    }
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=10)
        response.raise_for_status()

        # Download into memory
        pdf_file = io.BytesIO(response.content)

        try:
            reader = pypdf.PdfReader(pdf_file)
            if len(reader.pages) > 0:
                text = reader.pages[0].extract_text()
                # Check first 500 characters as per requirements (conceptually)
                # We return true if we got any significant text
                if text and len(text.strip()) > 0:
                    return True, text[:500]
        except Exception as e:
            print(f"PDF parsing error: {e}")
            return False, ""

    except Exception as e:
        print(f"Download error: {e}")
        return False, ""

    return False, ""

def main():
    parser = argparse.ArgumentParser(description="Aerospace Research Scraper")
    parser.add_argument("--download", action="store_true", help="Download full text PDFs if available")
    args = parser.parse_args()

    seen_ids = load_seen_ids()

    # Aggregate data sources
    nasa_results = fetch_nasa_data()
    faa_results = fetch_faa_data()
    arxiv_results = fetch_arxiv_data()
    openalex_results = fetch_openalex_data()

    all_results = nasa_results + faa_results + arxiv_results + openalex_results
    seen_ids = load_seen_ids()

    nasa_results = fetch_nasa_data()
    faa_results = fetch_faa_data()

    brave_api_key = os.environ.get("BRAVE_API_KEY")
    if brave_api_key:
        brave_results = fetch_brave_data("aerospace engineering structural analysis", brave_api_key)
    else:
        print("BRAVE_API_KEY not found. Skipping Brave Search.")
        brave_results = []

    all_results = nasa_results + faa_results + brave_results
    all_results = nasa_results + faa_results
    new_entries_count = 0

    for item in all_results:
        url = item.get("url")
        if not url:
            continue

        if url in seen_ids:
            continue

        title = item.get("title")
        source_name = item.get("source")
        abstract = item.get("abstract", "")
        relevance = item.get("relevance", "")

        # Verify PDF if it looks like one
        is_pdf_url = url.lower().endswith(".pdf")

        # AGENTS.md says: "When a PDF is found... verify it is readable text"
        # We'll check if it is a PDF URL.
        # Note: Some NASA URLs are landing pages, we only verify if it is a direct PDF link.

        readable = True
        if is_pdf_url:
            readable, text_sample = verify_pdf_readability(url)
            if not readable:
                print(f"Skipping unreadable PDF: {url}")
                continue

        # Format entry for log
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_entry = f"\n### [{date_str}] {title}\n"
        log_entry += f"**Source:** {url}\n"
        log_entry += f"**Relevance:** {relevance}\n"

        # Truncate abstract to first 3 sentences or reasonable length
        if abstract:
            # Simple sentence splitting
            sentences = abstract.replace('\r', '').replace('\n', ' ').split('. ')
            summary = ". ".join(sentences[:3])
            if len(sentences) > 3:
                summary += "..."
        else:
            summary = "No abstract available."

        log_entry += f"**Summary:**\n> {summary}\n---\n"

        # Append to Research_Log.md
        with open("Research_Log.md", "a") as f:
            f.write(log_entry)

        seen_ids.add(url)
        new_entries_count += 1

        # Download full text if enabled and it's a PDF
        if args.download and is_pdf_url:
            download_pdf(url, title)

    save_seen_ids(seen_ids)
    print(f"Process complete. Added {new_entries_count} new entries.")

if __name__ == "__main__":
    main()
