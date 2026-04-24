import json
from webscraper import fetch_arxiv_papers

def run_test():
    print("Initiating arXiv API Test...\n")

    # The exact query we built earlier
    test_query = '%28all:"computational biology" OR all:"drug discovery"%29 AND %28all:"in silico" OR all:"machine learning"%29'
    
    # We only request 2 papers for the test so we don't flood your terminal
    results = fetch_arxiv_papers(search_query=test_query, max_results=2)

    # If the list is empty, the try/except block caught an error
    if not results:
        print("\n Test failed: No results returned. Check your internet connection or the query syntax.")
        return

    # Print the results beautifully formatted so you can verify the structure
    print("\n Test Complete! Here is the exact data structure OpenClaw will evaluate:\n")
    print(json.dumps(results, indent=4))

if __name__ == "__main__":
    run_test()