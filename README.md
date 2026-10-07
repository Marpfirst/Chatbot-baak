# Chatbot BAAK

A hybrid chatbot for the academic administration office (BAAK) of Gunadarma University. Questions about schedules, exams, the academic calendar, class advisors and counter hours are matched with regex rules and answered from a Supabase database. Other questions are answered with retrieval-augmented generation over a small Markdown knowledge base, using Pinecone and an OpenAI model.

All code is in the `Baakbot kosongan` folder. This copy contains the application code and data only: there is no `.env`, no Dockerfile and no deployment configuration.

## What it does

- Classifies each question with regex patterns into intents: class schedule, final exam (UAS) schedule, lecturer schedule, class advisor, BAAK counter hours, academic calendar, course list, or LLM fallback.
- Extracts the class code (for example `1KA01`) from the question and checks it against a list of valid study program codes.
- Asks a follow-up question when a required detail such as the class is missing, and keeps the pending intent for the next message.
- Rule-based intents query Supabase tables: `jadwal_kuliah`, `jadwal_uas`, `wali_kelas`, `jadwal_loket`, `kalender_akademik`.
- Fallback questions are embedded with `text-embedding-3-small`, matched against a Pinecone index, and answered by `gpt-4o-mini` using the retrieved passages. Both model names are defaults in `app/config.py` and can be changed through environment variables.
- Keeps per-session conversation memory in process memory (last 3 exchanges, 30 minute timeout).
- Serves a simple web chat page and a JSON API.

## Stack

Python, FastAPI, Uvicorn, Pydantic Settings, Supabase Python client, Pinecone, OpenAI API, Jinja2 templates, plain JavaScript and CSS for the chat page. The scraping scripts use Selenium with undetected-chromedriver, Playwright, BeautifulSoup and pandas.

## Project structure

Paths are relative to `Baakbot kosongan/`.

- `app/main.py` - FastAPI app, static files, logging to `logs/chat.log`
- `app/api/routes.py` - chat page, `POST /api/chat`, `POST /api/session/clear`, `GET /api/health`
- `app/services/intent_classifier.py` - regex intent rules and class code parsing
- `app/services/database.py` - Supabase queries
- `app/services/llm_service.py` - embeddings, Pinecone search and upsert, answer generation
- `app/services/rag_ingestion.py` - splits the Markdown knowledge base into chunks for Pinecone
- `app/services/memory_manager.py` - session and conversation memory
- `app/utils/helpers.py` - formats database rows into chat answers
- `data/*.py` - scrapers for the BAAK website
- `data/csv_files/` - scraped class schedules, exam schedules, academic calendar, counter hours, class advisors
- `data/knowledge_base/` - two Markdown files on administrative and lecture services
- `templates/`, `static/` - chat page

## Running locally

```
cd "Baakbot kosongan"
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Create a `.env` file in `Baakbot kosongan/` first. Required variables: `SUPABASE_URL`, `SUPABASE_KEY`, `OPENAI_API_KEY`, `PINECONE_API_KEY`. Optional variables and their defaults are listed in `app/config.py`.

The app expects the Supabase tables and the Pinecone index to already hold data. This repository does not include a table schema or a script that loads the CSV files into Supabase, and the knowledge base ingestion in `rag_ingestion.py` is a service class with no command-line entry point. The scraper dependencies are not listed in `requirements.txt`.

## Data source

Schedules, exam dates, the academic calendar, counter hours and class advisors were scraped from `baak.gunadarma.ac.id` by the scripts in `data/`.
