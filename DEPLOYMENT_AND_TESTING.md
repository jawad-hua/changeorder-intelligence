# ChangeOrder Intelligence — Phase 5 deployment and testing

**Important:** This is a production-oriented technical demo, **not yet a secure public SaaS**. The existing endpoints have no authentication or per-user quotas. Do **not** expose an unauthenticated Groq-backed API to the open internet until authentication, server-side quotas, abuse protection and a data-processing review are added. CORS is not an authentication mechanism.

## Update an existing Windows installation

This release is an incremental replace patch. Copy the files from the ZIP into `D:\changeorder-intelligence`, keeping their relative paths. The ZIP contains no `.env`, `.venv`, user documents, `node_modules` or full project reinstallation.

**Backend (Windows CMD):**

```bat
cd /d D:\changeorder-intelligence\backend
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --reload
```

**Frontend (second CMD):**

```bat
cd /d D:\changeorder-intelligence\frontend
npm install
npm run build
npm run dev
```

Open `http://localhost:3000`; backend health: `http://127.0.0.1:8000/health`.

**Important settings:** Keep the existing `backend/.env` and `GROQ_API_KEY`. `GROQ_MODEL` serves PDF/DOCX/TXT text extraction; `GROQ_VISION_MODEL` serves **direct image uploads only**. The default Vision model may depend on your Groq account's current model access. Do not put provider secrets in `NEXT_PUBLIC_*` variables or source code. Set `frontend/.env.local` to `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` for local use (only if needed).

## Source routes and privacy

| Input | Text recognition | External transfer | Local requirement |
| --- | --- | --- | --- |
| Text PDF | PyMuPDF text layer | Extracted text to Groq | Python requirements |
| DOCX | python-docx text/tables | Extracted text to Groq | Python requirements |
| TXT | UTF-8 text | Extracted text to Groq | Python requirements |
| Direct PNG/JPEG/WEBP/TIFF | Groq Vision | **Photo to Groq Vision**, resulting transcript to Groq text model | No Tesseract required |
| Scanned PDF or embedded PDF/DOCX figures | Local Tesseract OCR fallback | OCR text to Groq | Local Tesseract executable required |

Extracted transcript matches are **not independent pixel verification**. Image/handwriting results must be checked against the actual photo. Groq handling may be governed by your provider agreement. No uploaded files or manual reviews are stored persistently by this application; server-side OCR can use short-lived temporary files. Browser memory loses work on refresh; **export JSON/CSV before closing**.

## Manual acceptance checks using your own authorized documents

1. Upload a text-based change-order PDF individually and confirm all figures against its source quotes/pages.
2. Upload its DOCX equivalent; validate words and figures. DOCX page numbers should be `null`.
3. Upload a JPG or PNG with printed English text; confirm Groq Vision's transcript panel is labeled appropriately, and that the exact image is previewed. Do not expect local Tesseract for direct photos.
4. Upload up to five PDF/DOCX/TXT/photo documents together; ensure failures are isolated and both the correct cost and currency from clearly labeled totals are present.
5. Try a document with contradictory explicitly labeled totals; the financial status should require manual review, **not** silently pick a value.
6. Check manual review correction notes and separate machine/human statuses; download both JSON and CSV, including mixed success/failure batches. Check CSV in spreadsheet software.
7. Test a non-document image, empty file, unsupported extension, oversized upload and invalid DOCX/PDF; the app should report a controlled error.
8. Run responsive UI checks at mobile width; verify readable glass panels, focus outlines and lightbox previews.

**OCR limits:** PDF up to 100 pages (at most 12 scanned-OCR pages), 10 MB/file, five files per batch, images up to 14 megapixels, 120,000 extracted characters. Full frontend Next.js production build must be verified locally or via included GitHub Actions workflow, because it could not be completed in the build environment.

## Optional backend Docker image

From the repository root:

```sh
docker build -t changeorder-backend ./backend
docker run --rm -p 8000:8000 --env-file backend/.env changeorder-backend
```

Docker bundles Tesseract for scanned-PDF fallback. It uses a non-root process and a single Uvicorn worker to minimize RAM use. `backend/.dockerignore` excludes credentials from the Docker build context, and the Dockerfile copies only its `app` and dependency manifest. On a cloud host use a secret environment variable for the Groq key and configure allowed origins precisely in `CORS_ORIGINS`.

**Before any public deployment:** add sign-in/session management; per-user/tenant rate and cost limits; abuse checks; malware scanning for document uploads; secure secret management; data retention and consent policy; monitoring; provider quota alerts; TLS, threat modeling and load testing. Groq can produce variable outputs, so test on authorized, varied real documents before relying on automated decisions.
