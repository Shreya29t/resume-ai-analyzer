from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
from groq import Groq
import json
import re

app = FastAPI()

# CORS (for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔑 GROQ API KEY
client = Groq(api_key="GROQ_API_KEY")


@app.get("/")
def home():
    return {"message": "Backend is working 🚀"}


@app.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    try:

        # ── Validate file type ──────────────────────────────
        if not file.filename.lower().endswith(".pdf"):
            return {"error": "Invalid file type. Please upload a PDF."}

        contents = await file.read()

        # ── Validate file size (10MB max) ───────────────────
        if len(contents) > 10 * 1024 * 1024:
            return {"error": "File too large. Maximum size is 10MB."}

        # ── Extract PDF text ────────────────────────────────
        try:
            pdf = fitz.open(stream=contents, filetype="pdf")
        except Exception:
            return {"error": "Could not read PDF. The file may be corrupted."}

        text = ""
        for page in pdf:
            text += page.get_text()

        text = text.strip()

        if not text or len(text) < 50:
            return {"error": "Could not extract text from this PDF. It may be image-based or empty."}

        text = text[:3000]

        # ── Groq prompt — asks for strict JSON ──────────────
        prompt = f"""
You are an expert ATS resume reviewer.

Analyze the resume below and respond ONLY with a valid JSON object.
No explanation, no markdown, no code block — just raw JSON.

Format:
{{
  "score": <integer between 0 and 100>,
  "strengths": [<exactly 3 short strings, one sentence each>],
  "weaknesses": [<exactly 3 short strings, one sentence each>],
  "suggestions": [<exactly 5 short strings, one sentence each>]
}}

Resume:
{text}
"""

        # ── Groq API call ───────────────────────────────────
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.choices[0].message.content.strip()

        # ── Parse JSON from response ────────────────────────
        # Strip markdown code fences if model adds them anyway
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: try to find JSON object anywhere in the response
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                # Last resort: return raw text for frontend old parser
                return {
                    "filename": file.filename,
                    "analysis": raw.split("\n")
                }

        # ── Validate and clamp values ───────────────────────
        score = int(data.get("score", 0))
        score = max(0, min(100, score))

        strengths   = data.get("strengths",   [])[:3]
        weaknesses  = data.get("weaknesses",  [])[:3]
        suggestions = data.get("suggestions", [])[:5]

        return {
            "filename": file.filename,
            "score": score,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "suggestions": suggestions
        }

    except Exception as e:
        return {"error": str(e)}