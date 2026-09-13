# Polar-is web interface

The first interface slice uses FastAPI for HTTP requests and a Vite-built
React/TypeScript application for the browser. FastAPI serves the production
frontend from `frontend/dist` so the application has one origin.

## Install

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
cd api/interface/frontend
npm install
npm run build
```

## Run the built application

From the repository root:

```bash
.venv/bin/uvicorn api.interface.app:app --reload
```

Open <http://127.0.0.1:8000>. The interactive API documentation is at
<http://127.0.0.1:8000/docs>.

## Develop the frontend

Run FastAPI on port 8000, then start Vite in a second terminal:

```bash
cd api/interface/frontend
npm run dev
```

Vite proxies `/api` requests to FastAPI. Rebuild the frontend before testing
the single-origin production form.

## Test

```bash
.venv/bin/python -m pytest
cd api/interface/frontend
npm run build
```
