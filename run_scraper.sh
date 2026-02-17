#!/bin/bash
# Example usage:
# export BRAVE_API_KEY="your_api_key_here"
# ./run_scraper.sh

if [ -z "$BRAVE_API_KEY" ]; then
  echo "Error: BRAVE_API_KEY environment variable is not set."
  echo "Usage: export BRAVE_API_KEY='your_key' && ./run_scraper.sh"
  echo "Or: BRAVE_API_KEY='your_key' ./run_scraper.sh"
  exit 1
fi

python3 scraper.py
