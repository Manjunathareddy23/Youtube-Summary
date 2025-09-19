# ------------------- Imports -------------------
import streamlit as st
import os
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import google.generativeai as genai
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ------------------- Environment -------------------
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# ------------------- Streamlit Setup -------------------
st.set_page_config(page_title="Gemini YouTube Summarizer", layout="wide")

# ------------------- Session State -------------------
defaults = {
    "current_video_id": None,
    "current_video_title": None,
    "current_transcript": None,
    "current_summary": None,
    "qa_history": [],
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ------------------- Prompts -------------------
CHUNK_PROMPT = """Analyze this transcript chunk and extract:
- Key points
- Important quotes
- Technical info
- Concepts
- Short summary

Chunk: """

FINAL_PROMPT = """Combine all the chunk summaries into a single detailed summary:
- Main topic/title
- Executive summary (200 words)
- Key points (10-20)
- Detailed analysis (1500-2000 words)
- Quotes, technical data, concepts

Provide structured output: """

FAST_SUMMARY_PROMPT = """Provide a concise executive summary (150-300 words). Skip technical data and quotes."""

# ------------------- Helper Functions -------------------
def get_youtube_video_id(url):
    """Extract YouTube video ID from URL."""
    url = url.strip()
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    parsed_url = urlparse(url)
    query = parse_qs(parsed_url.query)
    if 'v' in query:
        return query['v'][0]
    return None

def fetch_transcript(video_id):
    """Fetch transcript safely."""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join([t['text'] for t in transcript_list])
        return text
    except (TranscriptsDisabled, NoTranscriptFound, AttributeError):
        return None

def chunk_text(text, max_length=3000):
    """Split text into sentence chunks."""
    sentences = re.split(r'(?<=[.!?]) +', text)
    chunks = []
    current = ""
    for s in sentences:
        if len(current) + len(s) <= max_length:
            current += " " + s
        else:
            chunks.append(current.strip())
            current = s
    if current:
        chunks.append(current.strip())
    return chunks

def generate_content(text, prompt):
    """Call Gemini API for generation."""
    model = genai.GenerativeModel("gemini-1.5-flash-latest", generation_config={'temperature':0.5})
    try:
        response = model.generate_content(f"{prompt}\n\n{text}")
        cleaned = re.sub(r'\n{3,}', '\n\n', response.text)
        return cleaned
    except Exception as e:
        return f"Error generating content: {str(e)}"

def generate_detailed_summary(transcript):
    """Generate detailed summary in parallel chunks."""
    if not transcript:
        return "Transcript unavailable. Detailed notes cannot be generated."
    chunks = chunk_text(transcript)
    results = []
    progress = st.progress(0)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(generate_content, c, CHUNK_PROMPT): c for c in chunks}
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            results.append(result)
            progress.progress((i+1)/len(chunks))
    combined = "\n\n".join(results)
    return generate_content(combined, FINAL_PROMPT)

def generate_fast_summary(text):
    """Generate fast summary."""
    if not text:
        return "Transcript unavailable. Using video title only."
    return generate_content(text, FAST_SUMMARY_PROMPT)

def create_word_doc(summary, video_title, video_id, qa_history=None):
    doc = Document()
    doc.add_heading(f"Video Summary: {video_title}", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph(f"Video link: https://youtube.com/watch?v={video_id}")
    doc.add_paragraph()
    doc.add_paragraph(summary)
    if qa_history:
        doc.add_heading("Q&A", 1)
        for qa in qa_history:
            q = doc.add_paragraph(f"Q: {qa['question']}")
            a = doc.add_paragraph(f"A: {qa['answer']}")
    return doc

def get_word_binary(video_title, video_id, summary, qa_history):
    doc = create_word_doc(summary, video_title, video_id, qa_history)
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ------------------- UI -------------------
st.title("🎯 YouTube Video Summarizer (Gemini Flash)")

video_url = st.text_input("Paste YouTube URL here:")
video_id = get_youtube_video_id(video_url) if video_url else None

if video_id:
    if st.session_state.current_video_id != video_id:
        st.session_state.current_video_id = video_id
        st.session_state.current_transcript = fetch_transcript(video_id)
        st.session_state.current_video_title = f"Video {video_id}"

    if not st.session_state.current_transcript:
        st.warning("Transcript not available. Fast summary will use video title only.")
        text_for_summary = st.session_state.current_video_title
    else:
        text_for_summary = st.session_state.current_transcript

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Generate Detailed Notes") and st.session_state.current_transcript:
            st.session_state.current_summary = generate_detailed_summary(st.session_state.current_transcript)
            st.success("Detailed notes generated!")

    with col2:
        if st.button("Generate Fast Summary"):
            st.session_state.current_summary = generate_fast_summary(text_for_summary)
            st.success("Fast summary generated!")

    if st.session_state.current_summary:
        st.subheader("📄 Summary")
        st.text_area("Summary", st.session_state.current_summary, height=400)

        question = st.text_input("Ask a question about this video:")
        if question:
            answer = generate_content(question + "\n\nContext:\n" + text_for_summary, "")
            st.session_state.qa_history.append({'question': question, 'answer': answer})
            st.text_area("Answer", answer, height=150)

        col1, col2 = st.columns(2)
        with col1:
            word_binary = get_word_binary(st.session_state.current_video_title, video_id,
                                          st.session_state.current_summary, st.session_state.qa_history)
            st.download_button("📥 Download Word", word_binary,
                               f"{st.session_state.current_video_title}.docx")
