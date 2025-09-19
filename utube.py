# ---------------- 1️⃣ Imports ----------------
import streamlit as st
import os
import googleapiclient.discovery
from dotenv import load_dotenv
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from datetime import datetime
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re
import time
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------- 2️⃣ Streamlit Config ----------------
st.set_page_config(
    page_title="🎯 Gemini Flash YouTube Video Summary",
    page_icon="🎯",
    layout="wide"
)

# ---------------- 3️⃣ Load Env & Configure Gemini ----------------
load_dotenv(override=True)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# ---------------- 4️⃣ Session State Defaults ----------------
defaults = {
    "current_summary": None,
    "current_transcript": None,
    "current_video_id": None,
    "current_video_title": None,
    "qa_history": [],
    "fast_summary_generated": False,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ---------------- 5️⃣ Prompts ----------------
CHUNK_PROMPT = """Analyze this portion of the video transcript and provide:
1. Key points
2. Notable quotes with timestamps
3. Technical data or statistics
4. Important concepts
5. Brief summary

Transcript section: """

FINAL_PROMPT = """Based on all sections, provide a comprehensive summary with:
1. Main Topic
2. Executive Summary (200 words)
3. Key Points (10-20)
4. Detailed Analysis (2000 words)
5. Notable Quotes
6. Technical Data
7. Key Terms
8. Concepts & Frameworks
9. Timeline & Structure
10. Practical Applications

Please synthesize this complete summary: """

FAST_SUMMARY_PROMPT = """Provide a concise executive summary of the video transcript (200-500 words). Skip detailed quotes or technical terms."""

# ---------------- 6️⃣ Helper Functions ----------------
def get_youtube_video_id(url):
    """Extract video ID from various YouTube URL formats."""
    url = url.strip()
    if not url:
        return None
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]+)',
        r'(?:https?:\/\/)?(?:www\.)?m\.youtube\.com\/watch\?v=([a-zA-Z0-9_-]+)',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]+)',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]+)',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    if 'v' in query_params:
        return query_params['v'][0]
    if parsed_url.hostname == 'youtu.be':
        return parsed_url.path.lstrip('/')
    return None

@st.cache_data(show_spinner=False)
def get_video_title_cached(video_id):
    """Fetch video title and description using YouTube Data API."""
    fallback_title = f"Video ID: {video_id}"
    fallback_desc = ""
    try:
        youtube = googleapiclient.discovery.build(
            "youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY")
        )
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        snippet = response.get("items", [{}])[0].get("snippet", {})
        title = snippet.get("title", fallback_title)
        description = snippet.get("description", fallback_desc)
        return title, description
    except Exception:
        return fallback_title, fallback_desc

def format_transcript(transcript_list):
    """Format transcript list to single string with timestamps."""
    if not transcript_list:
        return None
    formatted_transcript = []
    for item in transcript_list:
        timestamp = int(item["start"])
        time_str = f"[{timestamp // 3600:02d}:{(timestamp % 3600) // 60:02d}:{timestamp % 60:02d}]"
        formatted_transcript.append(f"{time_str} {item['text']}")
    return " ".join(formatted_transcript)

def generate_content(text, prompt):
    """Generate content using Gemini."""
    if "gemini_model" not in st.session_state:
        st.session_state.gemini_model = genai.GenerativeModel(
            "gemini-1.5-flash-latest",
            generation_config={'temperature':0.7, 'top_p':0.8, 'top_k':40}
        )
    model = st.session_state.gemini_model
    try:
        response = model.generate_content(f"{prompt}\n\n{text}")
        return response.text
    except Exception as e:
        st.error(f"Error generating content: {str(e)}")
        return None

def chunk_text_smarter(text, max_length=3000):
    """Split transcript into smart chunks."""
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
    """Analyze transcript chunks in parallel."""
    chunks = chunk_text_smarter(transcript)
    chunk_analyses = []
    progress_bar = st.progress(0)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(generate_content, chunk, CHUNK_PROMPT): chunk for chunk in chunks}
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            if result:
                chunk_analyses.append(result)
            progress_bar.progress((i+1)/len(chunks))
    combined_analysis = "\n\n".join(chunk_analyses)
    return generate_content(combined_analysis, FINAL_PROMPT)

def generate_qa_response(question, transcript, summary):
    prompt = f"Question: {question}\n\nSummary:\n{summary}\n\nTranscript:\n{transcript}\n\nAnswer:"
    return generate_content(prompt, "")

def create_word_document(summary, video_title, video_id, qa_history=None):
    doc = Document()
    title = doc.add_heading(f"Video Summary: {video_title or 'Untitled'}", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph(f"Video Link: https://youtube.com/watch?v={video_id}")
    doc.add_paragraph()
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
    doc = create_word_document(summary, video_title, video_id, qa_history)
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

def create_markdown_download(summary, video_title, video_id, qa_history=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = f"# Video Summary: {video_title}\n\nGenerated on: {timestamp}\nVideo Link: https://youtube.com/watch?v={video_id}\n\n{summary}\n"
    if qa_history:
        md += "\n## Questions & Answers\n"
        for qa in qa_history:
            md += f"**Q: {qa['question']}**\n\nA: {qa['answer']}\n\n"
    md += "\n---\nGenerated using YouTube Video Summarizer"
    return md

# ---------------- 7️⃣ Main App ----------------
def main():
    st.markdown("<h1 style='text-align:center'>🎯 YouTube Video Summary</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center'>AI-Powered Video Analysis & Summarization</p>", unsafe_allow_html=True)

    youtube_link = st.text_input("Enter YouTube URL:")
    video_id = get_youtube_video_id(youtube_link) if youtube_link else None

    description = ""

    if video_id:
        if st.button("Process Video") or st.session_state.current_video_id != video_id:
            st.session_state.current_video_id = video_id
            st.session_state.current_video_title, description = get_video_title_cached(video_id)

            # Fetch transcript
            transcript_list = None
            try:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            except (TranscriptsDisabled, NoTranscriptFound, Exception):
                st.warning("Transcript not available. Fast summary will use video title & description.")

            st.session_state.current_transcript = format_transcript(transcript_list)

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
                answer = generate_qa_response(question, st.session_state.current_transcript, st.session_state.current_summary)
                st.session_state.qa_history.append({'question': question, 'answer': answer})
                st.text_area("Answer", answer, height=150)

            # Downloads
            col1, col2 = st.columns(2)
            with col1:
                word_binary = get_word_binary(video_id, st.session_state.current_summary, st.session_state.qa_history, st.session_state.current_video_title)
                st.download_button("📥 Download Word", word_binary, f"{st.session_state.current_video_title}.docx")

            with col2:
                markdown_text = create_markdown_download(st.session_state.current_summary, st.session_state.current_video_title, video_id, st.session_state.qa_history)
                st.download_button("📥 Download Markdown", markdown_text, f"{st.session_state.current_video_title}.md")

if __name__ == "__main__":
    main()
