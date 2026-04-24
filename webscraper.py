import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime
import subprocess
import os

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
    print(f"📡 Fetching from PubMed: {search_term}...")
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

    #wake up OpenClaw to process data
    print("\n Waking up OpenClaw Literature Evaluator...")
    try:
        # This simulates typing 'openclaw run ...' into the terminal
        subprocess.run([
            "openclaw", 
            "skills", 
            "LiteratureEvaluator",
            filename,
            "--base-url", "http://host.docker.internal:8080/v1",
            #"--api-key", "sk-local"
        ], check=True)
        print("\n Agent Evaluation Complete.")
        
    except subprocess.CalledProcessError as e:
        print(f"\n The agent crashed during evaluation: {e}")
    except FileNotFoundError:
        print("\n OpenClaw is not installed or not in the system PATH.")



if __name__ == "__main__":
    main()