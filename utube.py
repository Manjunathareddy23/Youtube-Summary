# ---------------- Part 1: Imports and Setup ----------------
import streamlit as st
import os
import googleapiclient.discovery
from dotenv import load_dotenv
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from datetime import datetime
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------- Config ----------------
RETRY_COUNT = 3
RETRY_DELAY = 2
load_dotenv(override=True)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

st.set_page_config(
    page_title="Gemini Flash YouTube Video Summary",
    page_icon="🎯",
    layout="wide"
)

# ---------------- Session State ----------------
if "gemini_model" not in st.session_state:
    st.session_state.gemini_model = genai.GenerativeModel(
        "gemini-1.5-flash-latest",
        generation_config={'temperature':0.7, 'top_p':0.8, 'top_k':40}
    )

for key in ["current_summary", "video_processed", "current_transcript", "current_video_id", "current_video_title", "qa_history"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ---------------- Prompts ----------------
CHUNK_PROMPT = "Analyze this portion of the video transcript and provide key points, quotes, technical data, and a brief summary:\n\n"
FINAL_PROMPT = "Based on all sections, generate a detailed comprehensive summary (2000 words) with main topic, key points, technical data, quotes, and applications:\n\n"
FAST_SUMMARY_PROMPT = "Provide a concise executive summary of this video (200-500 words), skip technical details:\n\n"

# ---------------- Helper Functions ----------------
def get_youtube_video_id(url):
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]+)',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_video_title_and_desc(video_id):
    """Fetch title and description via YouTube Data API"""
    try:
        youtube = googleapiclient.discovery.build(
            "youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY")
        )
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        snippet = response.get("items", [{}])[0].get("snippet", {})
        title = snippet.get("title", f"Video ID: {video_id}")
        desc = snippet.get("description", "")
        return title, desc
    except Exception:
        return f"Video ID: {video_id}", ""

def fetch_transcript(video_id):
    try:
        return YouTubeTranscriptApi.get_transcript(video_id)
    except (NoTranscriptFound, TranscriptsDisabled):
        return None

def format_transcript(transcript_list):
    if not transcript_list:
        return ""
    formatted = []
    for item in transcript_list:
        timestamp = int(item["start"])
        time_str = f"[{timestamp // 3600:02d}:{(timestamp % 3600) // 60:02d}:{timestamp % 60:02d}]"
        formatted.append(f"{time_str} {item['text']}")
    return " ".join(formatted)

def generate_content(prompt_text):
    try:
        response = st.session_state.gemini_model.generate_content(prompt_text)
        return re.sub(r'\n{3,}', '\n\n', response.text)
    except Exception as e:
        st.error(f"Error generating content: {str(e)}")
        return None

def chunk_text(text, max_length=3000):
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

def generate_detailed_summary(transcript_text):
    chunks = chunk_text(transcript_text)
    analyses = []
    progress_bar = st.progress(0)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_chunk = {executor.submit(generate_content, CHUNK_PROMPT + chunk): chunk for chunk in chunks}
        for i, future in enumerate(as_completed(future_to_chunk)):
            result = future.result()
            if result:
                analyses.append(result)
            progress_bar.progress((i+1)/len(chunks))
    combined = "\n\n".join(analyses)
    return generate_content(FINAL_PROMPT + combined)

def generate_fast_summary(transcript_text="", title_desc=""):
    """Use transcript if available; else use title+description"""
    text_to_use = transcript_text or title_desc
    if not text_to_use:
        text_to_use = "No transcript or description available. Generate a general summary of a YouTube video."
    return generate_content(FAST_SUMMARY_PROMPT + text_to_use)

# ---------------- Word/Markdown ----------------
def create_word(summary, video_title, video_id, qa_history=None):
    doc = Document()
    doc.add_heading(f"Video Summary: {video_title}", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Video Link: https://youtube.com/watch?v={video_id}")
    doc.add_paragraph()
    for line in summary.split("\n"):
        doc.add_paragraph(line.strip())
    if qa_history:
        doc.add_heading("Q&A", 1)
        for qa in qa_history:
            q = doc.add_paragraph()
            q.add_run("Q: ").bold = True
            q.add_run(qa['question'])
            a = doc.add_paragraph()
            a.add_run("A: ").bold = True
            a.add_run(qa['answer'])
            doc.add_paragraph()
    doc.add_paragraph("Generated using Gemini Flash AI").alignment = WD_ALIGN_PARAGRAPH.CENTER
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

def create_markdown(summary, video_title, video_id, qa_history=None):
    md = f"# Video Summary: {video_title}\nVideo Link: https://youtube.com/watch?v={video_id}\n\n{summary}\n"
    if qa_history:
        md += "\n## Q&A\n"
        for qa in qa_history:
            md += f"**Q: {qa['question']}**\n\nA: {qa['answer']}\n\n"
    md += "\n---\nGenerated using Gemini Flash AI"
    return md

# ---------------- Streamlit UI ----------------
st.title("🎯 YouTube Video Summary App")

youtube_url = st.text_input("Enter YouTube URL:")
video_id = get_youtube_video_id(youtube_url) if youtube_url else None

if video_id:
    if st.button("Process Video") or st.session_state.current_video_id != video_id:
        st.session_state.current_video_id = video_id
        st.session_state.current_video_title, video_desc = get_video_title_and_desc(video_id)
        transcript_list = fetch_transcript(video_id)
        st.session_state.current_transcript = format_transcript(transcript_list)
        if st.session_state.current_transcript:
            st.success(f"Transcript fetched: {st.session_state.current_video_title}")
        else:
            st.warning("Transcript not available. Fast summary will use video title/description.")
    
    # Summary generation
    if st.button("Generate Detailed Notes") and st.session_state.current_transcript:
        st.session_state.current_summary = generate_detailed_summary(st.session_state.current_transcript)
        st.success("Detailed summary generated!")

    if st.button("Generate Fast Summary"):
        title_desc_text = (st.session_state.current_video_title + ". " + video_desc) if video_id else ""
        st.session_state.current_summary = generate_fast_summary(st.session_state.current_transcript, title_desc_text)
        st.success("Fast summary generated!")

    # Show summary
    if st.session_state.current_summary:
        st.subheader("📄 Video Summary")
        st.text_area("Summary", st.session_state.current_summary, height=400)

        # QA Section
        question = st.text_input("Ask a question about this video:")
        if question:
            answer = generate_content(f"Question: {question}\n\nSummary:\n{st.session_state.current_summary}\n\nAnswer:")
            if answer:
                if st.session_state.qa_history is None:
                    st.session_state.qa_history = []
                st.session_state.qa_history.append({"question": question, "answer": answer})
                st.text_area("Answer", answer, height=150)

        # Download buttons
        col1, col2 = st.columns(2)
        with col1:
            word_binary = create_word(st.session_state.current_summary, st.session_state.current_video_title, video_id, st.session_state.qa_history)
            st.download_button("📥 Download Word", word_binary, f"{st.session_state.current_video_title}.docx")
        with col2:
            markdown_text = create_markdown(st.session_state.current_summary, st.session_state.current_video_title, video_id, st.session_state.qa_history)
            st.download_button("📥 Download Markdown", markdown_text, f"{st.session_state.current_video_title}.md")
