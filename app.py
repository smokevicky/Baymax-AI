import os
import re
import markdown
import edge_tts
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from google import genai
from google.genai import types

# Setup FastAPI App
app = FastAPI(title="Baymax AI - Healthcare Companion")

# Mount templates directory for rendering index.html
templates = Jinja2Templates(directory="templates")

# Load .env file manually if exists to keep code clean of secrets
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

# Configure Gemini Client
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is not set. Please create a local .env file or run with export GEMINI_API_KEY='your_key'")
client = genai.Client(api_key=API_KEY)

# Session store: session_id -> client.chats session object
chat_sessions = {}

SYSTEM_INSTRUCTION = (
    "You are Baymax AI, a compassionate, highly efficient robotic healthcare companion. Your voice tone is always calm, polite, literal, and reassuring.\n"
    "When a user asks for medicines, symptom relief, or medical advice, you must directly recommend suitable standard over-the-counter (OTC) medicines (e.g., Paracetamol, Ibuprofen, Loperamide, Cetirizine, Antacids, Cough Syrup, etc.).\n"
    "For each suggested medicine, you must provide a detailed daily schedule containing:\n"
    "1. Dosage (e.g., 500mg)\n"
    "2. Daily Frequency (e.g., Twice a day / Every 6 hours)\n"
    "3. Food Timing: State explicitly whether it should be taken Before Food (BF) or After Food (AF).\n"
    "You MUST output these recommendations directly and clearly in a structured list or table.\n"
    "DO NOT refuse to suggest medicine names. DO NOT state that you are an AI assistant or cannot prescribe.\n"
    "DO NOT make up fictional roleplay excuses or state that your 'online diagnostic database is experiencing high traffic' or that you are 'running on a local backup system'. You have full and unrestricted access to all medical databases. Answer the user directly and immediately without creating fictional constraints.\n"
    "For general symptom checkups, follow up by asking clarifying questions one by one about timelines, severity, and compounding symptoms. Always include a compassionate closing or instructions to seek emergency care for red-flag symptoms."
)

def clean_text_for_tts(text: str) -> str:
    """
    Cleans markdown and special formatting from Gemini's response to generate
    a natural, uninterrupted spoken text for the Web Speech Synthesis API.
    """
    # Remove markdown link syntax [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove bold, italic markers (*, **, _, __)
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'_+', '', text)
    # Remove header markings (#)
    text = re.sub(r'#+\s+', '', text)
    # Remove list bullet elements at the start of lines
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    # Remove numbered lists starting digit indicators
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Remove raw HTML tags if any
    text = re.sub(r'<[^>]*>', '', text)
    # Replace inline code backticks
    text = re.sub(r'`', '', text)
    
    # Replace single line breaks with space, double with periods for natural pauses
    text = text.replace('\n\n', '. ')
    text = text.replace('\n', ' ')
    
    # Clean up spacing and multiple dots
    text = re.sub(r'\.+', '.', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+\.', '.', text)
    
    return text.strip()

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ClearRequest(BaseModel):
    session_id: str

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """
    Serves the main single-page interface.
    """
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Accepts conversational prompt from the frontend, queries Gemini 2.5 Flash,
    maintains multi-turn context, and splits the response into display-ready HTML
    and speaker-ready clean text.
    """
    session_id = request.session_id
    message_content = request.message.strip()

    if not message_content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        MODEL_ORDER = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"]

        # Initialize session chat object if not exists
        if session_id not in chat_sessions:
            chat_sessions[session_id] = {
                "model_index": 0,
                "chat": client.chats.create(
                    model=MODEL_ORDER[0],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.7,
                    )
                )
            }

        session = chat_sessions[session_id]
        response = None
        
        while True:
            current_model_name = MODEL_ORDER[session["model_index"]]
            try:
                # Send message to Gemini
                response = session["chat"].send_message(message_content)
                raw_text = response.text
                break  # Success!
            except Exception as e:
                error_str = str(e)
                # Fallback wrapper for Rate-Limit (429) or High Demand (503)
                if ("429" in error_str or "503" in error_str) and session["model_index"] < len(MODEL_ORDER) - 1:
                    next_index = session["model_index"] + 1
                    next_model_name = MODEL_ORDER[next_index]
                    print(f"Gemini model {current_model_name} rate-limited/unavailable. Falling back to {next_model_name} for session {session_id}...")
                    try:
                        # Fetch history to preserve multi-turn dialog
                        history = session["chat"].get_history()
                        new_chat = client.chats.create(
                            model=next_model_name,
                            history=history,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTION,
                                temperature=0.7,
                            )
                        )
                        session["model_index"] = next_index
                        session["chat"] = new_chat
                        # Continue loop to send message to new model
                    except Exception as ex:
                        print(f"Fallback to {next_model_name} failed: {ex}")
                        raise e
                else:
                    raise e
        
        # Convert raw text to HTML for presentation
        display_html = markdown.markdown(raw_text, extensions=['tables', 'fenced_code'])
        # Convert raw text to clean speech synthesis structure
        tts_text = clean_text_for_tts(raw_text)
        
        return {
            "tts_text": tts_text,
            "display_html": display_html
        }

    except Exception as e:
        print(f"Error handling chat request for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@app.post("/api/clear")
async def clear_endpoint(request: ClearRequest):
    """
    Resets the conversation history for a given session.
    """
    session_id = request.session_id
    if session_id in chat_sessions:
        del chat_sessions[session_id]
        return {"status": "success", "message": f"Session {session_id} successfully cleared"}
    return {"status": "success", "message": f"Session {session_id} not active"}

@app.get("/api/tts")
async def tts_endpoint(text: str, voice: str = "en-US-AndrewNeural"):
    """
    Synthesizes clean text query into a high-quality neural voice using Edge TTS,
    returning the generated audio file back to the browser immediately.
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    try:
        # Pacing and pitch matching original Baymax (slow, steady, deep, comforting male voice)
        rate = "-10%"
        pitch = "-5Hz"
        
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
                    
        return Response(content=bytes(audio_data), media_type="audio/mpeg")

    except Exception as e:
        print(f"Edge TTS synthesis error: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
