import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime
import os
import secrets

MODEL_NAME = "gemini-2.5-flash"
PENDING_PAYLOAD_PATH = os.path.join("data", "pending_gemini_payload.json")
LATEST_EVALUATION_PATH = os.path.join("data", "latest_evaluation.json")
MAX_LINKS_IN_PROMPT = 15

# JSON schema for structured evaluation (Gemini REST: generationConfig.responseJsonSchema)
EVALUATION_RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "generatedAt": {
            "type": "string",
            "description": "ISO-8601 timestamp when this evaluation was produced.",
        },
        "topPapers": {
            "type": "array",
            "maxItems": 5,
            "description": "Ranked papers, highest score first (at most 5).",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer", "description": "1-based rank."},
                    "title": {"type": "string"},
                    "authors": {"type": "string"},
                    "source": {"type": "string", "description": "Source label, e.g. arXiv or PubMed."},
                    "url": {"type": "string"},
                    "score": {
                        "type": "integer",
                        "description": "Integer from 0 to 100 inclusive.",
                    },
                    "reason": {"type": "string"},
                },
                "required": [
                    "rank",
                    "title",
                    "authors",
                    "source",
                    "url",
                    "score",
                    "reason",
                ],
            },
        },
    },
    "required": ["generatedAt", "topPapers"],
}


def strip_yaml_frontmatter(markdown_text):
    """Remove leading OpenClaw-style YAML frontmatter (--- ... ---) from skill files."""
    if not markdown_text.startswith("---"):
        return markdown_text
    lines = markdown_text.splitlines()
    if len(lines) < 2 or lines[0].strip() != "---":
        return markdown_text
    for idx in range(1, min(len(lines), 50)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[idx + 1 :]).lstrip("\n")
    return markdown_text


# ==========================================
# 1. THE ADAPTERS (Database-Specific Fetchers)
# ==========================================

def fetch_arxiv_papers(search_query, max_results=5):
    """Fetches papers from arXiv API and normalizes the output."""
    print(f" Fetching from arXiv: {search_query}...")
    url = f"http://export.arxiv.org/api/query?search_query={search_query}&start=0&max_results={max_results}"

    normalized_results = []
    
    try:
        #fetch raw XML data w 10 sec timeout failsafe
        response = requests.get(url, timeout = 10)
        response.raise_for_status()

        # parse the raw XML into a searchable tree
        root = ET.fromstring(response.content)

        # define arXiv Atom namespace for parsing
        namespaces = {"atom" : "http://www.w3.org/2005/Atom"}

        # loop thru each entry 
        for entry in root.findall("atom:entry", namespaces):
            # extract data using namespace prefix of Atom
            title = entry.find("atom:title", namespaces).text.replace("\n", "").strip()
            abstract = entry.find("atom:summary", namespaces).text.replace("\n", "").strip()
            pdf_url = entry.find("atom:id", namespaces).text

            #authors are nested, so we go go go find and extract them
            authors = []
            for author in entry.findall("atom:author", namespaces):
                name = author.find("atom:name", namespaces).text
                authors.append(name)
            author_str = ", ".join(authors)

            normalized_results.append({
                "source": "arXiv",
                "title": title,
                "authors": author_str,
                "abstract": abstract,
                "url": pdf_url
            })

    except requests.exceptions.RequestException as e:
        print(f" Network Error fetching from arXiv: {e}")
    except ET.ParseError as e:
        print(f" XML Parsing Error from arXiv: {e}")
    except Exception as e:
        print(f" Unexpected Error: {e}")
    
    return normalized_results


def fetch_pubmed_papers(search_term, max_results=5):
    """Fetches papers from PubMed API (NCBI E-utilities) and normalizes output."""
    print(f" Fetching from PubMed: {search_term}...")
    # PubMed requires a two-step process: ESearch to get IDs, ESummary to get details
    # ... API request logic goes here ...
    
    normalized_results = []
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    
    try:
        #Esearch to get IDs in JSON format
        search_url = f"{base_url}/esearch.fcgi?db=pubmed&term={search_term}&retmax={max_results}&retmode=json"
        search_response = requests.get(search_url, timeout = 10)
        search_response.raise_for_status()

        #parse JSON and grab PMIDs
        id_list = search_response.json().get("esearchresult", {}).get("idlist", [])

        if not id_list:
            print(" No papers found in PubMed for this query.")
            return normalized_results
        
        ids_string = ",".join(id_list)
        fetch_url = f"{base_url}/efetch.fcgi?db=pubmed&id={ids_string}&retmode=xml"
        fetch_response = requests.get(fetch_url, timeout=10)
        fetch_response.raise_for_status()
        
        # Parse the raw bytes into a searchable XML tree
        root = ET.fromstring(fetch_response.content)
        
        # Loop through each article in the XML tree
        for article in root.findall('.//PubmedArticle'):
            
            # Extract Title
            title_elem = article.find('.//ArticleTitle')
            title = title_elem.text if title_elem is not None else "No Title"
            
            # Extract Abstract (Using .// to search anywhere inside the article tag)
            abstract_elem = article.find('.//AbstractText')
            abstract = abstract_elem.text if abstract_elem is not None else "No Abstract Available"
            
            # Extract URL using the PMID
            pmid_elem = article.find('.//PMID')
            pmid = pmid_elem.text if pmid_elem is not None else ""
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
            
            # Extract Authors (PubMed nests them, so we loop through again)
            authors = []
            for author in article.findall('.//Author'):
                last_name = author.find('LastName')
                initials = author.find('Initials')
                if last_name is not None and initials is not None:
                    authors.append(f"{last_name.text} {initials.text}")
                    
            authors_str = ", ".join(authors) if authors else "Unknown Authors"
            
            # Package it into your standardized dictionary format
            normalized_results.append({
                "source": "PubMed",
                "title": title,
                "authors": authors_str,
                "abstract": abstract,
                "url": url
            })

    except Exception as e:
        print(f" Error fetching from PubMed: {e}")
        
    return normalized_results


def build_compact_paper_list(papers, limit=MAX_LINKS_IN_PROMPT):
    compact = []
    for index, paper in enumerate(papers[:limit], start=1):
        compact.append({
            "index": index,
            "source": paper.get("source", "Unknown"),
            "title": paper.get("title", "Untitled"),
            "authors": paper.get("authors", "Unknown Authors"),
            "url": paper.get("url", ""),
        })
    return compact


def build_gemini_payload(rubric_prompt, compact_papers):
    prompt = (
        "Evaluate the following paper candidates using the system rubric. "
        "Use only the metadata and URLs provided (you cannot fetch URLs). "
        "Scores must be integers from 0 through 100.\n\n"
        "Return JSON matching the enforced response schema only. "
        "Include at most 5 items in topPapers, ranked best-first. "
        "Keep each reason under 280 characters. "
        "If no paper scores above 60, set topPapers to an empty array.\n\n"
        f"Papers:\n{json.dumps(compact_papers, indent=2)}"
    )
    return {
        "system_instruction": {
            "parts": [{"text": rubric_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "responseJsonSchema": EVALUATION_RESPONSE_JSON_SCHEMA,
        },
    }


def save_pending_payload(gemini_url, payload):
    os.makedirs("data", exist_ok=True)
    pending = {
        "gemini_url": gemini_url,
        "payload": payload,
        "saved_at": datetime.now().isoformat(),
    }
    with open(PENDING_PAYLOAD_PATH, "w", encoding="utf-8") as pending_file:
        json.dump(pending, pending_file, indent=2)


def save_latest_evaluation(evaluation_data):
    os.makedirs("data", exist_ok=True)
    with open(LATEST_EVALUATION_PATH, "w", encoding="utf-8") as output_file:
        json.dump(evaluation_data, output_file, indent=2)


def parse_gemini_json_response(ai_evaluation):
    try:
        return json.loads(ai_evaluation)
    except json.JSONDecodeError:
        start = ai_evaluation.find("{")
        end = ai_evaluation.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(ai_evaluation[start:end + 1])
        raise


def overwrite_then_delete(path):
    if not os.path.exists(path):
        return
    size = os.path.getsize(path)
    with open(path, "wb") as file_obj:
        if size > 0:
            file_obj.write(secrets.token_bytes(size))
            file_obj.flush()
    os.remove(path)


def send_gemini_request(gemini_url, payload):
    headers = {"Content-Type": "application/json"}
    response = requests.post(gemini_url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    return response


def extract_gemini_candidate_text(body):
    """Concatenate all `text` parts from the first candidate (Gemini may split JSON across parts)."""
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    cand = candidates[0]
    content = cand.get("content") or {}
    parts = content.get("parts") or []
    texts = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            texts.append(part["text"])
    joined = "".join(texts)
    return joined


def consume_pending_payload():
    """Retry a saved Gemini request. Never raises: returns True on success, False otherwise."""
    if not os.path.exists(PENDING_PAYLOAD_PATH):
        return False

    try:
        with open(PENDING_PAYLOAD_PATH, "r", encoding="utf-8") as pending_file:
            pending_data = json.load(pending_file)
    except json.JSONDecodeError as exc:
        print(f"\n Pending payload file is not valid JSON ({exc}). Skipping retry; fix or delete {PENDING_PAYLOAD_PATH}")
        return False
    except OSError as exc:
        print(f"\n Could not read pending payload file: {exc}")
        return False

    if not isinstance(pending_data, dict):
        print(f"\n Pending payload must be a JSON object. Skipping retry; check {PENDING_PAYLOAD_PATH}")
        return False
    try:
        gemini_url = pending_data["gemini_url"]
        payload = pending_data["payload"]
    except KeyError as exc:
        print(f"\n Pending payload missing required key {exc!r}. Skipping retry; check {PENDING_PAYLOAD_PATH}")
        return False

    print("\n Found pending Gemini payload. Retrying before new request...")
    try:
        response = send_gemini_request(gemini_url, payload)
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        print(f"\n Pending Gemini retry failed (HTTP {status}): {exc}")
        if exc.response is not None:
            print(f"Error Details: {exc.response.text}")
        return False
    except requests.exceptions.RequestException as exc:
        print(f"\n Pending Gemini retry failed (network): {exc}")
        return False

    try:
        body = response.json()
        ai_evaluation = extract_gemini_candidate_text(body)
        if not ai_evaluation.strip():
            print("\n Pending Gemini response had no text parts.")
            return False
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        print(f"\n Pending Gemini response could not be parsed: {exc}")
        return False

    try:
        parsed = parse_gemini_json_response(ai_evaluation)
        save_latest_evaluation(parsed)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"\n Pending Gemini output was not valid evaluation JSON: {exc}")
        return False
    except OSError as exc:
        print(f"\n Could not save latest evaluation after pending retry: {exc}")
        return False

    print("\n✅ Pending Gemini payload sent successfully:\n")
    print("=" * 50)
    print(ai_evaluation)
    print("=" * 50)
    try:
        overwrite_then_delete(PENDING_PAYLOAD_PATH)
        print("\n Pending payload file securely removed.")
    except OSError as exc:
        print(f"\n Evaluation saved but could not remove pending file: {exc}")
    return True


# ==========================================
# 2. THE PIPELINE ORCHESTRATOR
# ==========================================

def main():
    print("🚀 Initiating Daily Literature Pipeline...\n")
    all_papers = []
    
    # Execute searches using your specific research vectors
    arxiv_results = fetch_arxiv_papers(
        search_query='%28all:"computational biology" OR all:"drug discovery"%29 AND %28all:"in silico" OR all:"machine learning"%29', 
        max_results=10
    )
    
    pubmed_results = fetch_pubmed_papers(
        search_term = '("Neurobiology"[tiab] OR "neuromuscular diseases"[tiab] OR "regenerative medicine"[tiab]) AND ("computational"[tiab] OR "in silico"[tiab] OR "machine learning"[tiab] OR "software"[tiab])', 
        max_results=10
    )
    # Combine the lists
    all_papers.extend(arxiv_results)
    all_papers.extend(pubmed_results)
    
    # ==========================================
    # 3. THE HANDOFF (Saving for OpenClaw)
    # ==========================================
    
    if not all_papers:
        print("⚠️ No papers found today. Exiting.")
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"data/abstracts_{date_str}.json"
    os.makedirs("data", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(all_papers, f, indent=4)
        
    print(f"\n Pipeline Complete. {len(all_papers)} papers normalized and saved to {filename}")

    # API handoff to Gemini 
    print("\n Sending data directly to Gemini API...")
    
    #  Replace this with your actual Gemini API key. 
    # (If you push this to GitHub later, make sure to use os.environ.get("GEMINI_API_KEY") instead!)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    payload = None
    
    try:
        consume_pending_payload()

        skill_path = os.path.join("Skills", "skills.md")
        # 1. Read your OpenClaw Skill file to use as the "System Instruction"
        with open(skill_path, "r", encoding="utf-8") as skill_file:
            rubric_prompt = strip_yaml_frontmatter(skill_file.read())

        # 2. Build a compact payload with links-only metadata.
        compact_papers = build_compact_paper_list(all_papers)
        payload = build_gemini_payload(rubric_prompt, compact_papers)
        
        # 3. Fire the request directly to Google's servers
        response = send_gemini_request(gemini_url, payload)
        
        # If Gemini throws an error (like an invalid API key), this will catch it
        # 4. Extract and print the AI's response (merge all text parts)
        response_body = response.json()
        ai_evaluation = extract_gemini_candidate_text(response_body)
        if not ai_evaluation.strip():
            print("\n Gemini response contained no text in candidate parts.")
            return
        parsed = parse_gemini_json_response(ai_evaluation)
        save_latest_evaluation(parsed)
        
        print("\n✅ Gemini Evaluation Complete:\n")
        print("="*50)
        print(ai_evaluation)
        print("="*50)
        
        # (Later, you will forward 'ai_evaluation' to the WhatsApp API here!)

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code == 429:
            if payload is not None:
                save_pending_payload(gemini_url, payload)
                print(f" Saved request payload to '{PENDING_PAYLOAD_PATH}' for retry after quota reset.")
                print(" The pending payload will be overwritten and deleted after a successful resend.")
            else:
                print(" Pending payload already exists and could not be resent due to quota.")
            print("\n⚠️ Gemini quota exceeded (429).")
            return
        print(f"\n❌ Gemini API HTTP error: {e}")
        if e.response is not None:
            print(f"Error Details: {e.response.text}")
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Gemini API Connection failed: {e}")
        # Print the detailed error message from Google if available
        if hasattr(e, 'response') and e.response is not None:
            print(f"Error Details: {e.response.text}")
    except FileNotFoundError:
        print("\n❌ Could not find the SKILL file. Make sure 'Skills/skills.md' exists.")



if __name__ == "__main__":
    main()