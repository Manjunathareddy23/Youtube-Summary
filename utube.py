# ------------------- Imports -------------------
import streamlit as st
import os
import googleapiclient.discovery
from dotenv import load_dotenv
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
from datetime import datetime
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re
from urllib.parse import urlparse, parse_qs
import time

# ------------------- Constants -------------------
RETRY_COUNT = 4
RETRY_DELAY = 3

CHUNK_PROMPT = """Analyze this portion of the video transcript and provide:
1. Key points discussed
2. Notable quotes and spoken content with timestamps
3. Technical data, statistics
4. Important concepts
5. Brief summary
Transcript section: """

FINAL_PROMPT = """Based on all chunks, provide a comprehensive summary with:
1. Main Topic/Title
2. Executive Summary (200 words)
3. Key Points
4. Detailed Analysis (2000 words)
5. Notable Quotes & Key Statements
6. Technical Data & Statistics
7. Key Terms & Definitions
8. Concepts & Frameworks
9. Timeline & Structure
10. Practical Applications
Please synthesize this complete summary: """

FAST_SUMMARY_PROMPT = """Provide a concise executive summary of the video transcript.
- Limit 200-500 words
- Focus on main ideas, key insights, central theme
- Skip detailed quotes, technical terms"""

# ------------------- Streamlit Config -------------------
st.set_page_config(
    page_title="🎯 YouTube Video Summary App",
    page_icon="🎯",
    layout="wide"
)

# ------------------- Session State -------------------
for key in [
    "current_summary", "word_doc_binary", "video_processed",
    "current_transcript", "current_video_id", "current_video_title",
    "qa_history", "clear_input", "video_count", "query_count",
    "fast_summary_generated"
]:
    if key not in st.session_state:
        st.session_state[key] = None if "summary" in key or "binary" in key else False
st.session_state.video_count = st.session_state.video_count or 0
st.session_state.query_count = st.session_state.query_count or 0

# ------------------- Load API -------------------
load_dotenv(override=True)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# ------------------- Utility Functions -------------------
def get_youtube_video_id(url):
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
        if match: return match.group(1)
    parsed_url = urlparse(url)
    if parsed_url.hostname in ['www.youtube.com', 'youtube.com', 'm.youtube.com']:
        query_params = parse_qs(parsed_url.query)
        if 'v' in query_params:
            return query_params['v'][0]
    if parsed_url.hostname == 'youtu.be':
        return parsed_url.path.lstrip('/')
    return None

def get_youtube_title(video_id, youtube_link):
    fallback_title = f"Video ID: {video_id} ({youtube_link})"
    try:
        youtube = googleapiclient.discovery.build(
            "youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY")
        )
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        title = response.get("items", [{}])[0].get("snippet", {}).get("title")
        return title or fallback_title
    except:
        st.warning("⚠️ Error retrieving video title. Using Video ID fallback.")
        return fallback_title

def extract_transcript(video_id):
    for attempt in range(RETRY_COUNT):
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            formatted_transcript = []
            for item in transcript_list:
                start = int(item['start'])
                timestamp = f"[{start//3600:02d}:{(start%3600)//60:02d}:{start%60:02d}]"
                formatted_transcript.append(f"{timestamp} {item['text']}")
            return " ".join(formatted_transcript)
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            return None
        except Exception as e:
            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_DELAY)
                continue
            return None

def chunk_text(text, chunk_size=5000):
    words = text.split()
    chunks, current_chunk, length = [], [], 0
    for word in words:
        if length + len(word) + 1 <= chunk_size:
            current_chunk.append(word)
            length += len(word) + 1
        else:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            length = len(word)
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks

def format_response(response_text):
    cleaned = re.sub(r'\n{3,}', '\n\n', response_text)
    cleaned = re.sub(r'(?m)^\s*[-•]\s*', '- ', cleaned)
    return cleaned

def generate_content(text, prompt, retry_count=3):
    if not text or not text.strip():
        return "⚠️ Transcript empty. Cannot generate summary."
    formatted_prompt = f"{prompt}\n\n{text}\n\nInstructions: Be precise, relevant, no filler, include timestamps where available."
    for attempt in range(retry_count):
        try:
            model = genai.GenerativeModel("gemini-1.5-flash-latest",
                                          generation_config={"temperature":0.3, "top_p":0.9, "top_k":40})
            response = model.generate_content(formatted_prompt)
            formatted_response = format_response(response.text)
            if len(formatted_response) < 50 and attempt < retry_count-1:
                continue
            return formatted_response
        except:
            if attempt == retry_count-1:
                return "⚠️ Error generating content."
            time.sleep(2)

def analyze_transcript(transcript):
    if not transcript:
        return "⚠️ No transcript available."
    chunks = chunk_text(transcript)
    st.write(f"📝 Splitting transcript into {len(chunks)} chunks...")
    progress_bar = st.progress(0)
    all_summaries = []
    for i, chunk in enumerate(chunks):
        st.write(f"Analyzing chunk {i+1}...")
        chunk_summary = generate_content(chunk, CHUNK_PROMPT)
        if chunk_summary:
            all_summaries.append(chunk_summary)
        progress_bar.progress((i+1)/len(chunks))
    combined = "\n\n".join(all_summaries)
    st.write("Generating final detailed notes...")
    return generate_content(combined, FINAL_PROMPT)

def generate_fast_summary(transcript):
    return generate_content(transcript, FAST_SUMMARY_PROMPT)

# ------------------- Streamlit UI -------------------
def main():
    st.title("🎯 YouTube Video Summary App")
    youtube_link = st.text_input("Enter YouTube Video URL:")
    if not youtube_link:
        st.info("Paste a YouTube URL above to start analysis.")
        return

    video_id = get_youtube_video_id(youtube_link)
    if not video_id:
        st.error("❌ Invalid YouTube URL.")
        return

    if video_id != st.session_state.current_video_id:
        st.session_state.current_video_id = video_id
        st.session_state.current_video_title = get_youtube_title(video_id, youtube_link)
        st.session_state.current_transcript = extract_transcript(video_id)
        st.session_state.current_summary = None
        st.session_state.fast_summary_generated = False
        st.session_state.video_processed = False
        st.session_state.qa_history = []

    st.subheader(f"Video: {st.session_state.current_video_title}")
    st.image(f"http://img.youtube.com/vi/{video_id}/0.jpg", use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("⚡ Fast Summary"):
            if st.session_state.current_transcript:
                st.session_state.current_summary = generate_fast_summary(st.session_state.current_transcript)
                st.session_state.fast_summary_generated = True
                st.session_state.video_processed = False
            else:
                st.warning("Transcript unavailable. Using title & description for fast summary.")
    with col2:
        if st.button("🚀 Detailed Notes"):
            if st.session_state.current_transcript:
                st.session_state.current_summary = analyze_transcript(st.session_state.current_transcript)
                st.session_state.video_processed = True
                st.session_state.fast_summary_generated = False
            else:
                st.warning("Transcript unavailable. Cannot generate detailed notes.")

    if st.session_state.current_summary:
        st.markdown("### 📝 Generated Summary")
        st.write(st.session_state.current_summary)

        # Download options
        markdown_content = f"# {st.session_state.current_video_title}\n\n{st.session_state.current_summary}"
        st.download_button("Download Markdown", markdown_content, f"{video_id}.md", "text/markdown")

        doc = Document()
        doc.add_heading(st.session_state.current_video_title, 0)
        for line in st.session_state.current_summary.split("\n"):
            p = doc.add_paragraph(line)
            p.paragraph_format.space_after = Pt(2)
        f = io.BytesIO()
        doc.save(f)
        st.download_button("Download Word Document", f.getvalue(), f"{video_id}.docx")

main()
