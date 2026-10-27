Gemini Desktop Chatbot
A desktop chat app built with Python and tkinter that uses the Google Gemini API, so you can ask questions in a window without opening a browser.

Features
·	Multi-turn conversation memory
·	Formatted replies (bold, headings, lists, code blocks)
·	Background threading, so the UI never freezes
·	Dark/light theme, copy-reply and new-chat buttons
Setup
git clone https://github.com/Pankajkumar3708/AI-study-assistant.git
cd AI-study-assistant
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"     # Windows: set GEMINI_API_KEY=your-key
python desktop_chatbot.py

Get a free key from Google AI Studio. Set GEMINI_MODEL to change the model (default gemini-3.1-flash). Run python check_setup.py to test your key.
Notes
Never commit your API key; it is read from an environment variable only.
