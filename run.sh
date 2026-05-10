#!/bin/bash
cd "$(dirname "$0")"
streamlit run main.py --server.port 8501 --server.headless false
