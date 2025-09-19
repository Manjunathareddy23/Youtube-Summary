# ------------------- Imports -------------------
import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
import pytube
from transformers import pipeline
import nltk
from nltk.tokenize import word_tokenize
import readtime
import textstat
import re

# ------------------- NLTK setup -------------------
nltk.download('punkt')

# ------------------- Summarization Pipeline -------------------
summarization = pipeline("summarization")

# ------------------- Helper Functions -------------------

def get_transcript(video_url):
    """Retrieve transcript text from a YouTube video URL"""
    try:
        video_id = pytube.extract.video_id(video_url)
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        corpus = " ".join([element["text"].replace("\n", " ") for element in transcript_list])
        return corpus
    except Exception as e:
        st.warning("⚠️ Could not retrieve transcript. It may be disabled or unavailable.")
        return None

def get_metadata(video_url):
    """Return author, keywords, length, views, description"""
    try:
        yt_object = YouTube(video_url)
        author = yt_object.author
        keywords = yt_object.keywords
        length = yt_object.length
        views = yt_object.views
        description = yt_object.description
        return author, keywords, length, views, description
    except Exception as e:
        st.warning("⚠️ Could not retrieve video metadata.")
        return None, None, None, None, None

def get_summary(corpus, max_length=150):
    """Generate summary using HuggingFace transformers"""
    if not corpus:
        return "⚠️ No transcript available to summarize."
    try:
        summary_text = summarization(corpus, max_length=max_length)[0]['summary_text']
        return summary_text
    except Exception as e:
        st.warning("⚠️ Error during summarization.")
        return None

def get_summary_analysis(summary):
    """Return reading time, text complexity, lexical richness, number of sentences"""
    if not summary:
        return None, None, None, None
    try:
        read_time = readtime.of_text(summary)
        text_complexity = textstat.flesch_reading_ease(summary)
        tokenized_words = word_tokenize(summary)
        lexical_richness = round(len(set(tokenized_words)) / len(tokenized_words), 2) if tokenized_words else 0
        num_sentences = textstat.sentence_count(summary)
        return read_time, text_complexity, lexical_richness, num_sentences
    except Exception as e:
        st.warning("⚠️ Error during summary analysis.")
        return None, None, None, None

# ------------------- Streamlit App -------------------

st.title("🎯 YouTube Summarizer")
st.header("This application helps you get the summary of a YouTube video.")

video_url = st.text_input(
    "Enter YouTube video URL: [Try https://www.youtube.com/watch?v=_FdDgJAw-YM]"
)

if st.button("Get Summary"):

    # ---------------- Video Section ----------------
    st.header("Video")
    with st.expander("Watch Video"):
        st.video(video_url)

    # ---------------- Metadata Section ----------------
    st.header("Metadata")
    with st.expander("View Metadata"):
        author, keywords, length, views, description = get_metadata(video_url)
        st.subheader("Author"); st.write(author)
        st.subheader("Keywords"); st.write(keywords)
        st.subheader("Length (seconds)"); st.write(length)
        st.subheader("Views"); st.write(views)
        st.subheader("Description"); st.write(description)

    # ---------------- Transcript Section ----------------
    transcript_corpus = get_transcript(video_url)
    st.header("Transcript")
    with st.expander("View Transcript"):
        st.write(transcript_corpus or "Transcript unavailable.")

    # ---------------- Summary Section ----------------
    if transcript_corpus:
        summary = get_summary(transcript_corpus)
        st.header("Summary")
        with st.expander("View Summary"):
            st.write(summary or "Summary unavailable.")

        # ---------------- Summary Analysis ----------------
        read_time, text_complexity, lexical_richness, num_sentences = get_summary_analysis(summary)
        st.header("Summary Analysis")
        with st.expander("View Analysis"):
            st.subheader("Estimated Reading Time"); st.write(read_time)
            st.subheader("Text Complexity (Flesch Reading Ease)")
            st.text("Values range 0 or negative (hard) to 100+ (easy)")
            st.write(text_complexity)
            st.subheader("Lexical Richness (Unique Words / Total Words)"); st.write(lexical_richness)
            st.subheader("Number of Sentences"); st.write(num_sentences)

        st.balloons()

# ------------------- Footer -------------------
hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    footer:after {
        content:"Made with 💓 by ManjunathaReddy"; 
        visibility: visible;
        display: block;
        position: relative;
        padding: 5px;
        top: 2px;
    }
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
