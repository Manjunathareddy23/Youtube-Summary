# ---------------- 1️⃣ Imports and Setup ----------------
import streamlit as st
import os
import re
import io
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled, CouldNotRetrieveTranscript
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from dotenv import load_dotenv
import google.generativeai as genai
import googleapiclient.discovery

# ---------------- 2️⃣ Streamlit Page Config ----------------
st.set_page_config(
    page_title="Gemini Flash YouTube Video Summary",
    page_icon="🎯",
    layout="wide"
)

# ---------------- 3️⃣ Session State Defaults ----------------
session_defaults = {
    "current_summary": None,
    "video_processed": False,
    "current_transcript": None,
    "current_video_id": None,
    "current_video_title": None,
    "qa_history": [],
    "fast_summary_generated": False
}

for key, value in session_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ---------------- 4️⃣ Load API Keys ----------------
load_dotenv(override=True)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

# Initialize Gemini model
if "gemini_model" not in st.session_state:
    st.session_state.gemini_model = genai.GenerativeModel(
        "gemini-1.5-flash-latest",
        generation_config={'temperature':0.7, 'top_p':0.8, 'top_k':40}
    )

# ---------------- 5️⃣ Prompts ----------------
CHUNK_PROMPT = """Analyze this portion of the video transcript and provide:
1. Key points discussed
2. Notable quotes with timestamps
3. Technical data or statistics
4. Important concepts and definitions
5. Brief summary

Transcript section: """

FINAL_PROMPT = """Based on all sections, provide a comprehensive summary including:
1. Main Topic/Title
2. Executive Summary (200 words)
3. Key Points (10-20)
4. Detailed Analysis (2000 words)
5. Notable Quotes and Key Statements
6. Technical Data & Statistics
7. Key Terms & Definitions
8. Concepts & Frameworks
9. Timeline & Structure
10. Practical Applications

Synthesize the complete summary: """

FAST_SUMMARY_PROMPT = "Provide a concise executive summary (200-500 words). Skip detailed quotes or technical terms."

# ---------------- 6️⃣ Helper Functions ----------------
def get_youtube_video_id(url):
    """Extract video ID from URL."""
    if not url:
        return None
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]+)',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    # Fallback
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    if 'v' in query_params:
        return query_params['v'][0]
    if parsed_url.hostname == 'youtu.be':
        return parsed_url.path.lstrip('/')
    return None

@st.cache_data(show_spinner=False)
def get_video_title_cached(video_id):
    """Fetch video title using YouTube API."""
    try:
        youtube = googleapiclient.discovery.build(
            "youtube", "v3", developerKey=YOUTUBE_API_KEY
        )
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        snippet = response.get("items", [{}])[0].get("snippet", {})
        title = snippet.get("title")
        description = snippet.get("description", "")
        return title or f"Video ID: {video_id}", description
    except Exception:
        return f"Video ID: {video_id}", ""

def fetch_transcript(video_id):
    """Safely fetch transcript; return None if unavailable."""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        return transcript_list
    except (NoTranscriptFound, TranscriptsDisabled, CouldNotRetrieveTranscript):
        return None
    except Exception as e:
        st.warning(f"Warning: Transcript could not be retrieved ({str(e)}). Fast summary will be used.")
        return None

def format_transcript(transcript_list):
    """Convert transcript list to text string with timestamps."""
    if not transcript_list:
        return None
    formatted = []
    for item in transcript_list:
        ts = int(item["start"])
        time_str = f"[{ts//3600:02d}:{(ts%3600)//60:02d}:{ts%60:02d}]"
        formatted.append(f"{time_str} {item['text']}")
    return " ".join(formatted)

def generate_content(text, prompt):
    """Generate content using Gemini model."""
    model = st.session_state.gemini_model
    try:
        response = model.generate_content(f"{prompt}\n\n{text}")
        return response.text
    except Exception as e:
        st.error(f"Error generating content: {str(e)}")
        return None

def chunk_text(text, max_length=3000):
    """Split text into smart chunks."""
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

def analyze_transcript_parallel(transcript):
    """Analyze transcript in parallel chunks."""
    chunks = chunk_text(transcript)
    chunk_results = []
    progress = st.progress(0)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(generate_content, c, CHUNK_PROMPT): c for c in chunks}
        for i, future in enumerate(as_completed(futures)):
            res = future.result()
            if res:
                chunk_results.append(res)
            progress.progress((i+1)/len(chunks))
    combined = "\n\n".join(chunk_results)
    return generate_content(combined, FINAL_PROMPT)

def generate_qa_response(question, transcript, summary):
    """Generate answer for user question."""
    prompt = f"Question: {question}\n\nSummary:\n{summary}\n\nTranscript:\n{transcript}\n\nAnswer:"
    return generate_content(prompt, "")

def create_word_document(summary, video_title, video_id, qa_history=None):
    """Generate Word doc."""
    doc = Document()
    doc.add_heading(f"Video Summary: {video_title}", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph(f"Video Link: https://youtube.com/watch?v={video_id}\n")
    for line in summary.split("\n"):
        doc.add_paragraph(line.strip())
    if qa_history:
        doc.add_heading("Questions & Answers", 1)
        for qa in qa_history:
            q_para = doc.add_paragraph()
            q_para.add_run("Q: ").bold = True
            q_para.add_run(qa['question'])
            a_para = doc.add_paragraph()
            a_para.add_run("A: ").bold = True
            a_para.add_run(qa['answer'])
    return doc

def get_word_binary(video_id, summary, qa_history, video_title):
    """Return Word doc binary."""
    key = f"word_{video_id}"
    if key in st.session_state:
        return st.session_state[key]
    doc = create_word_document(summary, video_title, video_id, qa_history)
    bio = io.BytesIO()
    doc.save(bio)
    st.session_state[key] = bio.getvalue()
    return st.session_state[key]

def create_markdown_download(summary, video_title, video_id, qa_history=None):
    """Generate markdown content."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = f"# Video Summary: {video_title}\n\nGenerated on: {ts}\nVideo Link: https://youtube.com/watch?v={video_id}\n\n{summary}\n"
    if qa_history:
        md += "\n## Questions & Answers\n"
        for qa in qa_history:
            md += f"**Q: {qa['question']}**\n\nA: {qa['answer']}\n\n"
    md += "\n---\nGenerated using YouTube Video Summarizer"
    return md

# ---------------- 7️⃣ Streamlit UI ----------------
def main():
    st.title("🎯 YouTube Video Summary (Gemini Flash AI)")

    youtube_link = st.text_input("Enter YouTube URL:")
    video_id = get_youtube_video_id(youtube_link) if youtube_link else None

    if video_id:
        if st.button("Process Video") or st.session_state.current_video_id != video_id:
            st.session_state.current_video_id = video_id
            title, description = get_video_title_cached(video_id)
            st.session_state.current_video_title = title

            transcript_list = fetch_transcript(video_id)
            st.session_state.current_transcript = format_transcript(transcript_list)

            if st.session_state.current_transcript:
                st.success(f"Transcript fetched: {st.session_state.current_video_title}")
            else:
                st.warning("Transcript not available. Fast summary will use video title & description.")

        if st.session_state.current_transcript or st.session_state.current_video_title:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Generate Detailed Notes") and st.session_state.current_transcript:
                    st.session_state.current_summary = analyze_transcript_parallel(st.session_state.current_transcript)
                    st.success("Detailed summary generated!")
            with col2:
                if st.button("Generate Fast Summary"):
                    text_for_summary = st.session_state.current_transcript or (st.session_state.current_video_title + "\n" + description)
                    st.session_state.current_summary = generate_content(text_for_summary, FAST_SUMMARY_PROMPT)
                    st.success("Fast summary generated!")

        if st.session_state.current_summary:
            st.subheader("📄 Video Summary")
            st.text_area("Summary", st.session_state.current_summary, height=400)

            # QA
            question = st.text_input("Ask a question about this video:")
            if question:
                answer = generate_qa_response(question, st.session_state.current_transcript or "", st.session_state.current_summary)
                st.session_state.qa_history.append({'question': question, 'answer': answer})
                st.text_area("Answer", answer, height=150)

            # Download
            col1, col2 = st.columns(2)
            with col1:
                word_bin = get_word_binary(video_id, st.session_state.current_summary, st.session_state.qa_history, st.session_state.current_video_title)
                st.download_button("📥 Download Word", word_bin, f"{st.session_state.current_video_title}.docx")
            with col2:
                md_text = create_markdown_download(st.session_state.current_summary, st.session_state.current_video_title, video_id, st.session_state.qa_history)
                st.download_button("📥 Download Markdown", md_text, f"{st.session_state.current_video_title}.md")

if __name__ == "__main__":
    main()
