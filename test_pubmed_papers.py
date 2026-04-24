import json
from webscraper import fetch_pubmed_papers

def run_test():
    print(" Initiating PubMed API Test...\n")

    # Using the highly targeted query we built earlier
    test_query = '("Neurobiology"[tiab] OR "neuromuscular diseases"[tiab] OR "regenerative medicine"[tiab]) AND ("computational"[tiab] OR "in silico"[tiab] OR "machine learning"[tiab] OR "software"[tiab])'
    
    # Keeping it to 2 results to ensure we don't anger the NCBI rate limiters
    results = fetch_pubmed_papers(search_term=test_query, max_results=2)

    if not results:
        print("\n Test failed: No results returned. Check your internet connection or the query syntax.")
        return

    print("\n Test Complete! Here is the exact data structure OpenClaw will evaluate:\n")
    print(json.dumps(results, indent=4))

if __name__ == "__main__":
    run_test()