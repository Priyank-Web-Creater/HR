import os
import streamlit as st
import pdfplumber
import docx
import pandas as pd
from tempfile import NamedTemporaryFile
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq
from langchain.chains import LLMChain
import fitz 
from io import BytesIO
import warnings
warnings.filterwarnings("ignore", message="CropBox missing from /Page, defaulting to MediaBox")
import logging
logging.getLogger("pdfminer").setLevel(logging.ERROR)


#import exceptions

# Set up Groq LLM
model_api_key = st.secrets["groq_api_key"]
llm = ChatGroq(groq_api_key=model_api_key,model="llama3-8b-8192", temperature=0)

# Prompt template
prompt = PromptTemplate.from_template("""
You are a resume parser. Extract the following information from the given resume text:
- Full Name (First Name and Last Name)
- Email
- Phone (include country code if available)
- Location
- Years of Experience

Return *only* a valid JSON object. Do not include any explanation, markdown, or commentary.
Return the output in JSON format like this:
{{
    "Name": "...",
    "Email": "...",
    "Phone": "...",
    "Location": "...",
    "Years of Experience": "..."
}}

Resume Text:
\"\"\"
{resume_text}
\"\"\"
""")

chain = prompt | llm

# Extract text from PDF
def extract_text_from_pdf(file):
    # with pdfplumber.open(file) as pdf:
    #     return "\n".join(page.extract_text() or "" for page in pdf.pages)
    text = ""
    doc = fitz.open(file)
    for page in doc:
        text += page.get_text()  # gets all text including headers/footers
    return text.strip()

# Extract text from DOCX
def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join(p.text for p in doc.paragraphs)

# Main App
st.title("Wisdom Square Resume Parser")

uploaded_files = st.file_uploader("Upload Resume Files (PDF or DOCX)", type=["pdf", "docx"], accept_multiple_files=True)

if uploaded_files:
    results = []

    for file in uploaded_files:
        # Save to temp file
        with NamedTemporaryFile(delete=False, suffix="." + file.name.split(".")[-1]) as tmp:
            tmp.write(file.read())
            tmp_path = tmp.name

        # Extract text
        ext = file.name.split(".")[-1].lower()
        if ext == "pdf":
            resume_text = extract_text_from_pdf(tmp_path)
        elif ext == "docx":
            resume_text = extract_text_from_docx(tmp_path)
        else:
            st.warning(f"Unsupported file type: {ext}")
            continue

        # Call LLM
        with st.spinner(f"Parsing {file.name}..."):
            response = chain.invoke({"resume_text": resume_text})
            try:
                parsed = eval(response.content)  # assuming clean JSON-like response
                parsed["File Name"] = file.name
                results.append(parsed)
            except Exception as e:
                st.error(f"Failed to parse {file.name}: {e}")

        os.remove(tmp_path)

    # Display results
    if results:
        df = pd.DataFrame(results)
        st.success("✅ Parsing Complete!")
        st.dataframe(df)


        # Create a BytesIO buffer
        output = BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        output.seek(0)

        # Streamlit download button
        st.download_button(
            label="📥 Download Excel",
            data=output,
            file_name="parsed_resumes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
