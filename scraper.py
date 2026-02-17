import requests
import json
import os
from datetime import datetime, timedelta
import io
import pypdf

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

    save_seen_ids(seen_ids)
    print(f"Process complete. Added {new_entries_count} new entries.")

if __name__ == "__main__":
    main()
