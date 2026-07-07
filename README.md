# Baymax AI - Multimodal Speech-to-Speech Healthcare Companion

Baymax AI is a comfort-focused, production-ready speech-to-speech AI Health Assistant inspired by the beloved robotic companion Baymax from *Big Hero 6*. 

Built with **FastAPI** for a lightweight async backend, Google's modern **`google-genai` SDK** utilizing `gemini-2.5-flash` for clinical reasoning, and a **Vanilla HTML5/CSS3/JS frontend** incorporating custom WebGL shaders and browser-native Web Speech APIs.

---

## 🌟 Key Features

### 1. WebGL-Powered Home Dashboard
- **Interactive Noise Threads**: Renders 40 organic glowing crimson threads flowing using 2D Perlin Noise, shifting fluidly on cursor movement.
- **Horizontal Capabilities Slider**: Replaced default vertical scrolling with a single-viewport, auto-playing capabilities carousel featuring:
  - **Personal AI Doctor**: Launches immediate diagnostic checkups.
  - **Lab Test Interpretation**: Prompts users to analyze blood, urine, or medical reports.
  - **AI Symptom Checker**: Checks symptoms in everyday language.
- **Gradient Cover Mask**: A smooth linear gradient matching the off-white background (`#faf9f6`) completely masks the threads on the left side to ensure maximum text readability.

### 2. Multi-Page Architecture & Clean Routes
- **`/` / `/home`**: Main capabilities dashboard.
- **`/consult`**: Live speech consultation terminal. Topic selections redirect to clean path configurations (e.g. `/consult?topic=Labs` or `/consult?topic=Symptoms`) without long query strings.

### 3. Native Multimodal PDF Report Analysis
- **Circular Upload Button (`+`)**: Integrated next to the input message bar on the consult page.
- **Gemini GenAI Files API Integration**: Uploads PDFs directly to Gemini's native document container for clinical analysis.
- **Session-Persisted File References**: Tracks active file uploads to prevent premature file deletion, enabling continuous multi-turn follow-up questions (e.g., *"What does that glucose level mean?"*) without crashing.
- **Cloud Cleanup**: File references are automatically deleted from Gemini's storage when the user clears their session history.

### 4. Comfort Voice Assistant UI
- **Comforting Robotic Voice**: Integrated Edge-TTS neural voice synthesis with sentence-prefetching buffer mechanisms, achieving **under 200ms latency**.
- **Continuous Listening**: Voice recognition with silence tolerance so you aren't cut off mid-thought.
- **Dynamic Face Shaders**: Eye graphics blinking, glowing, and morphing into active waveform states to represent talking, thinking, and listening states.

---

## 🛠️ Installation & Local Setup

### 1. Clone & Navigate
```bash
git clone https://github.com/smokevicky/Baymax-AI.git
cd Baymax-AI
```

### 2. Setup Virtual Environment
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
```bash
pip install -r requirements.txt
```

### 4. Run the Server
```bash
python app.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## 🚀 Live 1-Click Deployments

### Vercel Deployment (Serverless)
This repository is configured out-of-the-box for **Vercel Serverless Functions** via [vercel.json](file:///Users/jyoti.jena/Documents/Repos/Baymax-AI/vercel.json):
1. Install Vercel CLI: `npm i -g vercel`.
2. Run `vercel --prod` in the project root directory.
3. Add the `GEMINI_API_KEY` under your Vercel Project Environment Settings.
4. *Vercel-specific enhancements (like writing temporary files to `/tmp` and tracking `.gitkeep` for static folders) are already automated.*

### Docker/Render Deployment
Use the optimized [Dockerfile](file:///Users/jyoti.jena/Documents/Repos/Baymax-AI/Dockerfile) to deploy on Render, Koyeb, or Hugging Face Spaces:
- **Build Command**: Automatically reads Docker container build settings.
- **Environment Key**: Set `GEMINI_API_KEY` inside your cloud host environment variables panel.
