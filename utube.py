# ---------------- Part 1: Imports ----------------
import streamlit as st
import os
from dotenv import load_dotenv
import googleapiclient.discovery
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
from datetime import datetime
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re
import time
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------- Config ----------------
RETRY_COUNT = 3
RETRY_DELAY = 2

st.set_page_config(page_title="Gemini Flash YouTube Summary", page_icon="🎯", layout="wide")

# ---------------- Session Defaults ----------------
session_defaults = {
    "current_summary": None,
    "word_doc_binary": None,
    "video_processed": False,
    "current_transcript": None,
    "current_video_id": None,
    "current_video_title": None,
    "qa_history": [],
    "fast_summary_generated": False,
}
for key, value in session_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ---------------- Load Env & Configure Gemini ----------------
load_dotenv(override=True)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# ---------------- Prompts ----------------
CHUNK_PROMPT = """Analyze this portion of the transcript and provide key points, quotes, statistics, and a brief summary.\nTranscript section:"""
FINAL_PROMPT = """Based on all chunk analyses, create a full comprehensive summary including main topic, executive summary, key points, detailed analysis, quotes, data, key terms, concepts, timeline, and applications."""
FAST_SUMMARY_PROMPT = "Provide a concise executive summary (200-500 words) skipping detailed quotes or technical terms."

# ---------------- Helper Functions ----------------
def get_youtube_video_id(url):
    """Extract video ID from URL"""
    url = url.strip()
    if not url:
        return None
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]+)',
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
    fallback_title = f"Video ID: {video_id}"
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY"))
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        title = response.get("items", [{}])[0].get("snippet", {}).get("title")
        return title if title else fallback_title
    except Exception:
        return fallback_title

def retry_transcript_extraction(video_id, retries=RETRY_COUNT, delay=RETRY_DELAY):
    for attempt in range(retries):
        try:
            return YouTubeTranscriptApi.get_transcript(video_id)
        except Exception:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                return None

@st.cache_data(show_spinner=False)
def get_transcript_cached(video_id):
    transcript_list = retry_transcript_extraction(video_id)
    if not transcript_list:
        return None
    formatted_transcript = []
    for item in transcript_list:
        timestamp = int(item["start"])
        time_str = f"[{timestamp // 3600:02d}:{(timestamp % 3600) // 60:02d}:{timestamp % 60:02d}]"
        formatted_transcript.append(f"{time_str} {item['text']}")
    return " ".join(formatted_transcript)

def format_response(response_text):
    cleaned = re.sub(r'\n{3,}', '\n\n', response_text)
    cleaned = re.sub(r'(?m)^\s*[-•]\s*', '- ', cleaned)
    return cleaned

if "gemini_model" not in st.session_state:
    st.session_state.gemini_model = genai.GenerativeModel(
        "gemini-1.5-flash-latest",
        generation_config={'temperature':0.7, 'top_p':0.8, 'top_k':40}
    )

def generate_content(text, prompt):
    model = st.session_state.gemini_model
    try:
        response = model.generate_content(f"{prompt}\n\n{text}")
        return format_response(response.text)
    except Exception as e:
        st.error(f"Error generating content: {str(e)}")
        return None

def chunk_text_smarter(text, max_length=3000):
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
    chunks = chunk_text_smarter(transcript)
    chunk_analyses = []
    progress_bar = st.progress(0)
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_chunk = {executor.submit(generate_content, chunk, CHUNK_PROMPT): chunk for chunk in chunks}
        for i, future in enumerate(as_completed(future_to_chunk)):
            result = future.result()
            if result:
                chunk_analyses.append(result)
            progress_bar.progress((i+1)/len(chunks))
    combined_analysis = "\n\n".join(chunk_analyses)
    return generate_content(combined_analysis, FINAL_PROMPT)

def generate_qa_response(question, transcript, summary):
    prompt = f"Question: {question}\n\nSummary:\n{summary}\n\nTranscript:\n{transcript}\n\nAnswer:"
    return generate_content(prompt, "")

# ---------------- Document Generation ----------------
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
            doc.add_paragraph()
    doc.add_paragraph()
    footer = doc.add_paragraph("Generated using YouTube Video Summarizer")
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return doc

def get_word_binary(video_id, summary, qa_history, video_title):
    key = f"word_{video_id}"
    if key in st.session_state:
        return st.session_state[key]
    doc = create_word_document(summary, video_title, video_id, qa_history)
    bio = io.BytesIO()
    doc.save(bio)
    st.session_state[key] = bio.getvalue()
    return st.session_state[key]

def create_markdown_download(summary, video_title, video_id, qa_history=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    markdown_content = f"# Video Summary: {video_title}\n\nGenerated on: {timestamp}\nVideo Link: https://youtube.com/watch?v={video_id}\n\n{summary}\n"
    if qa_history:
        markdown_content += "\n## Questions & Answers\n"
        for qa in qa_history:
            markdown_content += f"**Q: {qa['question']}**\n\nA: {qa['answer']}\n\n"
    markdown_content += "\n---\nGenerated using YouTube Video Summarizer"
    return markdown_content

# ---------------- Streamlit UI ----------------
def main():
    st.title("🎯 YouTube Video Summarizer")
    youtube_link = st.text_input("Enter YouTube URL:")
    video_id = get_youtube_video_id(youtube_link) if youtube_link else None
    
    if video_id:
        if st.button("Process Video") or st.session_state.current_video_id != video_id:
            st.session_state.video_processed = False
            st.session_state.current_video_id = video_id
            st.session_state.current_video_title = get_video_title_cached(video_id)
            st.session_state.current_transcript = get_transcript_cached(video_id)
            if st.session_state.current_transcript:
                st.success(f"Transcript fetched: {st.session_state.current_video_title}")
                st.session_state.video_processed = True
            else:
                st.error("Transcript not available for this video.")
        
        if st.session_state.video_processed:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Generate Detailed Notes"):
                    st.session_state.current_summary = analyze_transcript_parallel(st.session_state.current_transcript)
                    st.success("Detailed summary generated!")
            with col2:
                if st.button("Generate Fast Summary"):
                    st.session_state.current_summary = generate_content(st.session_state.current_transcript, FAST_SUMMARY_PROMPT)
                    st.success("Fast summary generated!")
        
        if st.session_state.current_summary:
            st.subheader("📄 Video Summary")
            st.text_area("Summary", st.session_state.current_summary, height=400)

            # QA
            question = st.text_input("Ask a question about this video:")
            if question:
                answer = generate_qa_response(question, st.session_state.current_transcript, st.session_state.current_summary)
                st.session_state.qa_history.append({'question': question, 'answer': answer})
                st.success("Answer generated!")
                st.text_area("Answer", answer, height=150)

            # Downloads
            col1, col2 = st.columns(2)
            with col1:
                word_binary = get_word_binary(video_id, st.session_state.current_summary, st.session_state.qa_history, st.session_state.current_video_title)
                safe_title = re.sub(r'[\\/*?:"<>|]', "", st.session_state.current_video_title)
                st.download_button("📥 Download Word", word_binary, f"{safe_title}.docx")
            with col2:
                markdown_text = create_markdown_download(st.session_state.current_summary, st.session_state.current_video_title, video_id, st.session_state.qa_history)
                st.download_button("📥 Download Markdown", markdown_text, f"{safe_title}.md")

if __name__ == "__main__":
    main()
