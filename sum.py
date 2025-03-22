import streamlit as st
from pytube import YouTube
from transformers import pipeline

# Function to extract captions from YouTube video
def get_youtube_captions(url):
    try:
        yt = YouTube(url)
        caption = yt.captions.get_by_language_code('en')  # Fetching English captions
        if caption:
            return caption.generate_srt_captions()
        else:
            return None
    except Exception as e:
        return str(e)

# Function to generate summary from text
def generate_summary(text):
    summarizer = pipeline("summarization")
    summary = summarizer(text, max_length=150, min_length=50, do_sample=False)
    return summary[0]['summary_text']

# Streamlit App
def main():
    st.title("YouTube Video Summarizer")

    # Input box for the user to paste YouTube URL
    youtube_url = st.text_input("Paste YouTube URL here:")

    if youtube_url:
        st.write("Processing video...")

        # Get video captions (subtitles)
        captions = get_youtube_captions(youtube_url)
        
        if captions:
            st.write("Captions fetched. Summarizing...")

            # Summarize captions
            summary = generate_summary(captions)
            st.write("Summary of the video:")
            st.write(summary)
        else:
            st.write("No captions available for this video. Please try another video.")

if __name__ == "__main__":
    main()
