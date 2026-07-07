# Baymax AI - Speech-to-Speech Healthcare Companion

Baymax AI is a complete, production-ready speech-to-speech AI Health Assistant inspired by the comforting robotic companion Baymax from Big Hero 6. It uses FastAPI for a lightweight async backend, the modern `google-genai` SDK with `gemini-2.5-flash` for multi-turn medical diagnostics, and a responsive HTML5/CSS3/Vanilla JS frontend integrating browser-native Web Speech APIs.

## Features
- **Ultra-Clean Baymax UI**: Features a beautiful white interface with the iconic Baymax eyes.
- **Dynamic Waveform Connector**: Connects the eyes and morphs into a pulsing CSS soundwave when listening or speaking, and returns to a static flat line when idle.
- **Speech Interactivity**: Integrated continuous Speech-to-Text (`SpeechRecognition`) and Text-to-Speech (`SpeechSynthesis`) with natural, comforting, robotic pacing.
- **Smart Dialogue & clinical guidelines**: Gemini 2.5 Flash behaves like a real doctor (asks clarifying timeline, severity, and compound symptom questions one-by-one rather than rushed diagnosis), dynamically structures lists/schedules, and includes health warnings/emergency indicators.
- **Robust Fallbacks**: Graceful fallback to inline keyboard/text input in case microphone permissions are disabled or the browser lacks Web Speech compatibility. Works on desktop, mobile, macOS, and Windows.

---

## Installation & Setup

Follow these steps to run the application locally on macOS or Windows:

### 1. Clone or Navigate to the Directory
Ensure you are in the application root directory:
```bash
cd /Users/jyoti.jena/Documents/Repos/Baymax-AI
```

### 2. Set Up a Virtual Environment (Recommended)
Creating a virtual environment ensures Python package containment:

**On macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**On Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
Install all required modules specified in `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 4. Configure the Gemini API Key
The application initializes the Gemini client using the environment variable `GEMINI_API_KEY`. If this environment variable is not defined, it automatically falls back to the preset API key provided.

To set your custom key:

**On macOS / Linux:**
```bash
export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
```

**On Windows (Command Prompt):**
```cmd
set GEMINI_API_KEY=YOUR_GEMINI_API_KEY
```

**On Windows (PowerShell):**
```powershell
$env:GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
```

---

## Running the Server

Start the FastAPI application utilizing Uvicorn:
```bash
python app.py
```
Or run directly through Uvicorn:
```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Once running, open your browser and navigate to:
**[http://localhost:8000](http://localhost:8000)**

---

## Multi-Device & Browser Guidance
1. **Localhost requirement**: Modern browsers (Chrome, Edge, Safari, Firefox) restrict Web Speech (Microphone) access to secure contexts. Running on `localhost` or `127.0.0.1` counts as secure and works out-of-the-box.
2. **Initial Click Gesture**: Browsers block audio playback before a user gesture. Click the **Wake Up Baymax** button to initialize the audio stream and activate speech recognition.
3. **Permissions**: Ensure you click "Allow" when the browser prompts for microphone access.
