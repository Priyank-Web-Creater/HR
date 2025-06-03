import os
import streamlit as st
import fitz  # PyMuPDF for PDF parsing
import docx
import pandas as pd
import json
from tempfile import NamedTemporaryFile
from io import BytesIO
from groq import Groq
import logging
import warnings
import re
import time

# Suppress warnings
warnings.filterwarnings("ignore", message="CropBox missing from /Page, defaulting to MediaBox")
logging.getLogger("pdfminer").setLevel(logging.ERROR)


# Initialize Groq client
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# System prompt for resume parsing
system_prompt = """
You are a resume parser. Extract the following information from the given resume text:
- Full Name (First Name and Last Name)
- Email
- Phone (include country code if available, default to +91)
- Location
- Years of Experience

Return only a valid JSON object.
Do not include any extra text, explanation, or markdown.

Respond with:
{
  "Name": "...",
  "Email": "...",
  "Phone": "...",
  "Location": "...",
  "Years of Experience": "..."
  Do not return any explanation, markdown, or additional text.
}
"""

# Extract text from PDF using PyMuPDF
def extract_text_from_pdf(path):
    doc = fitz.open(path)
    return "\n".join(page.get_text() for page in doc)

# Extract text from DOCX
def extract_text_from_docx(path):
    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs)

# Streaming response from Groq
def stream_resume_parse(resume_text):
    response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": resume_text}
        ],
        stream=True
    )

    streamed_text = ""
    for chunk in response:
        content = chunk.choices[0].delta.content or ""
        streamed_text += content
        yield content

# Utility function to extract JSON from LLM response
def extract_json_from_response(text):
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        json_str = match.group()
        json_str = json_str.replace("'", '"')
        json_str = re.sub(r",\s*([\]}])", r"\1", json_str)
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None

# Streamlit UI
st.title("📄 Wisdom Square Resume Parser")

uploaded_files = st.file_uploader(
    "Upload Resume Files (PDF or DOCX)",
    type=["pdf", "docx"],
    accept_multiple_files=True
)

if uploaded_files:
    results = []
    total_files = len(uploaded_files)
    counter_placeholder = st.empty()
    parsed_count = 0
    counter_placeholder.metric("Resumes Parsed", parsed_count, f"of {total_files}")

    for file in uploaded_files:
        ext = file.name.split(".")[-1].lower()

        with NamedTemporaryFile(delete=False, suffix="." + ext) as tmp:
            tmp.write(file.read())
            tmp_path = tmp.name

        if ext == "pdf":
            resume_text = extract_text_from_pdf(tmp_path)
        elif ext == "docx":
            resume_text = extract_text_from_docx(tmp_path)
        else:
            st.warning(f"Unsupported file type: {ext}")
            continue

        os.remove(tmp_path)


        #st.subheader(f"📝 Parsing `{file.name}`...")
        streamed_json = ""
        with st.spinner("Generating response..."):
            for token in stream_resume_parse(resume_text):
                streamed_json += token

        # Try to load and fix the streamed JSON, with retries
        max_retries = 2
        attempt = 0
        parsed = None

        while attempt <= max_retries:
            parsed = extract_json_from_response(streamed_json)
            if parsed:
                break
            else:
                attempt += 1
                time.sleep(1)
                st.warning(f"Retrying parse for {file.name} (attempt {attempt})...")
                streamed_json = ""
                for token in stream_resume_parse(resume_text):
                    streamed_json += token

        if parsed:
            parsed["File Name"] = file.name
            results.append(parsed)
            parsed_count += 1
            counter_placeholder.metric("Resumes Parsed", parsed_count, f"of {total_files}")
        else:
            st.error(f"❌ Failed to parse JSON for {file.name} after {max_retries + 1} attempts.")

    # Display and download results
    if results:
        df = pd.DataFrame(results)
        st.success("✅ Parsing Complete!")
        st.dataframe(df)

        output = BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        output.seek(0)

        st.download_button(
            label="📥 Download Excel",
            data=output,
            file_name="parsed_resumes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
