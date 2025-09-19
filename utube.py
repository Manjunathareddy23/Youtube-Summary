import streamlit as st
import os, io, re, time
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
from dotenv import load_dotenv
import google.generativeai as genai
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ------------------- Session State -------------------
if "summary" not in st.session_state: st.session_state.summary = None
if "transcript" not in st.session_state: st.session_state.transcript = None
if "video_id" not in st.session_state: st.session_state.video_id = None
if "video_title" not in st.session_state: st.session_state.video_title = None
if "word_doc" not in st.session_state: st.session_state.word_doc = None
if "qa_history" not in st.session_state: st.session_state.qa_history = []
if "fast_summary" not in st.session_state: st.session_state.fast_summary = None
if "video_count" not in st.session_state: st.session_state.video_count = 0
if "query_count" not in st.session_state: st.session_state.query_count = 0

# ------------------- Load API -------------------
load_dotenv()
API_KEY = st.secrets.get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    st.error("Missing Google AI API key!")
    st.stop()
genai.configure(api_key=API_KEY)

# ------------------- Utility Functions -------------------
def get_video_id(url: str) -> str | None:
    """Extract video ID from any YouTube URL format."""
    try:
        url = url.strip()
        patterns = [
            r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
        ]
        for p in patterns:
            m = re.search(p, url)
            if m: return m.group(1)
        parsed = urlparse(url)
        return parse_qs(parsed.query).get("v", [parsed.path.strip("/")])[0]
    except: return None

def fetch_transcript(video_id: str, retries=3) -> str | None:
    """Fetch transcript with retry."""
    for _ in range(retries):
        try:
            data = YouTubeTranscriptApi.get_transcript(video_id)
            return " ".join([f"[{int(x['start'])//60}:{int(x['start'])%60:02d}] {x['text']}" for x in data])
        except (TranscriptsDisabled, NoTranscriptFound): return None
        except: time.sleep(2)
    return None

def generate_gemini_content(text: str, prompt: str) -> str:
    """Call Gemini API."""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash-latest",
                                      generation_config={'temperature':0.7,'top_p':0.8,'top_k':40})
        resp = model.generate_content(f"{prompt}\n{text}")
        return re.sub(r'\n{3,}', '\n\n', resp.text)
    except Exception as e:
        st.warning(f"API Error: {e}")
        return ""

def create_word(summary: str, qa_history: list, video_title: str, video_id: str) -> bytes:
    """Generate Word file in-memory."""
    doc = Document()
    doc.add_heading(f"Video Summary: {video_title}", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph(f"Link: https://youtube.com/watch?v={video_id}\n")
    doc.add_paragraph(summary)
    if qa_history:
        doc.add_heading("Q&A", 1)
        for qa in qa_history:
            p = doc.add_paragraph(f"Q: {qa['question']}", style='List Bullet')
            p = doc.add_paragraph(f"A: {qa['answer']}", style='List Number')
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ------------------- Streamlit UI -------------------
st.title("🎯 YouTube Video Summarizer")
yt_url = st.text_input("Enter YouTube link:")

if yt_url:
    vid_id = get_video_id(yt_url)
    if vid_id != st.session_state.video_id:
        st.session_state.video_id = vid_id
        st.session_state.video_title = vid_id  # fallback
        st.session_state.transcript = fetch_transcript(vid_id)
        st.session_state.summary = None
        st.session_state.fast_summary = None
        st.session_state.qa_history = []

    if st.session_state.transcript:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⚡ Fast Summary"):
                st.session_state.fast_summary = generate_gemini_content(
                    st.session_state.transcript, "Provide concise 200-500 word summary."
                )
                st.session_state.summary = st.session_state.fast_summary
        with col2:
            if st.button("🚀 Detailed Notes"):
                st.session_state.summary = generate_gemini_content(
                    st.session_state.transcript, "Analyze transcript and provide detailed summary."
                )

        if st.session_state.summary:
            st.success("Summary Generated ✅")
            st.markdown(st.session_state.summary)

            # Download Buttons
            md = st.session_state.summary
            st.download_button("📥 Markdown", data=md, file_name=f"{vid_id}.md", mime="text/markdown")
            if not st.session_state.word_doc:
                st.session_state.word_doc = create_word(md, st.session_state.qa_history, st.session_state.video_title, vid_id)
            st.download_button("📄 Word", data=st.session_state.word_doc,
                               file_name=f"{vid_id}.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
