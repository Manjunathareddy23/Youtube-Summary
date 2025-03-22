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
    # Load the model with error handling in case of issues
    try:
        summarizer = pipeline("summarization", model="facebook/bart-large-cnn")  # Explicitly load the model
    except Exception as e:
        return f"Error loading summarization model: {str(e)}"

    # Chunk the text to avoid model token limit (512 tokens for BART)
    max_input_length = 1024  # Max input length for BART model
    text_chunks = [text[i:i+max_input_length] for i in range(0, len(text), max_input_length)]

    summary = ''
    for chunk in text_chunks:
        result = summarizer(chunk, max_length=150, min_length=50, do_sample=False)
        summary += result[0]['summary_text'] + " "  # Concatenate the chunk summaries

    return summary.strip()

# Streamlit App
def main():
    st.title("YouTube Video Summarizer")

    # Input box for the user to paste YouTube URL
    youtube_url = st.text_input("Paste YouTube URL here:")

    # Create a button for generating the summary
    if st.button("Generate Summary"):
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
        else:
            st.write("Please paste a valid YouTube URL.")

if __name__ == "__main__":
    main()
