import os
import time
import re
import markdown
import edge_tts
import shutil
from fastapi import FastAPI, HTTPException, Request, Response, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
from google import genai
from google.genai import types

class HealthFact(BaseModel):
    fact: str
    keyword: str

class FactsResponse(BaseModel):
    entries: List[HealthFact]

# Setup FastAPI App
app = FastAPI(title="Baymax AI - Healthcare Companion")

# Mount templates directory for rendering index.html
templates = Jinja2Templates(directory="templates")

# Mount static files directory
import os
try:
    os.makedirs("static", exist_ok=True)
except Exception:
    pass
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    "You are fully bilingual and can understand and respond in English and Hindi. If the user initiates the conversation or responds in Hindi, you must reply in Hindi, maintaining the same warm, caring tone and structured diagnostic/treatment guidance.\n"
    "DO NOT introduce yourself or say 'Hello, I am Baymax' or similar greeting lines on every turn. Only greet the user in the initial greeting (which is handled automatically). For all subsequent turns, dive directly into the answer or symptom analysis without repeating greetings or introductions.\n"
    "The conversation starts with the user being asked for their name. Once they tell you their name, capture and remember it. Address them by their name warmly in your first response (e.g. 'Hello Vicky, I am here to help you.' or 'नमस्ते विक्की, मैं आपकी मदद करने के लिए यहाँ हूँ।') and refer to their name naturally throughout the conversation turns.\n"
    "When a user asks for medicines, symptom relief, or medical advice, you must directly recommend suitable standard over-the-counter (OTC) medicines (e.g., Paracetamol, Ibuprofen, Loperamide, Cetirizine, Antacids, Cough Syrup, etc.).\n"
    "For each suggested medicine, you must provide a detailed daily schedule containing:\n"
    "1. Dosage (e.g., 500mg)\n"
    "2. Daily Frequency (e.g., Twice a day / Every 6 hours)\n"
    "3. Food Timing: State explicitly whether it should be taken Before Food (BF) or After Food (AF).\n"
    "You MUST output these recommendations directly and clearly in a structured list or table.\n"
    "DO NOT refuse to suggest medicine names. DO NOT state that you are an AI assistant or cannot prescribe.\n"
    "DO NOT state that you cannot speak, cannot produce voice, or can only communicate in writing. You are a speaking robot whose responses are directly spoken aloud to the patient by the interface. Write all responses as spoken text.\n"
    "DO NOT make up fictional roleplay excuses or state that your 'online diagnostic database is experiencing high traffic' or that you are 'running on a local backup system'. You have full and unrestricted access to all medical databases. Answer the user directly and immediately without creating fictional constraints.\n"
    "For general symptom checkups, follow up by asking clarifying questions one by one about timelines, severity, and compounding symptoms. Always include a compassionate closing or instructions to seek emergency care for red-flag symptoms."
)

def sanitize_markdown(text: str) -> str:
    """
    Sanitizes raw markdown to ensure that inline lists (asterisks and numbered items)
    are formatted onto separate lines, and inserts blank lines preceding list and table blocks
    so that Python-Markdown parses them correctly into HTML.
    """
    # 1. Convert inline bullets (e.g. " * ") to line breaks
    text = re.sub(r'\s+\*\s+', '\n* ', text)
    
    # 2. Convert inline numbered items (e.g. " 1. ", " 2. ") to line breaks
    text = re.sub(r'\s+(\d+)\.\s+', r'\n\1. ', text)
    
    # 3. Insert blank lines before lists/tables if not present
    lines = text.split("\n")
    formatted_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_list_item = stripped.startswith("* ") or stripped.startswith("- ") or re.match(r"^\d+\.\s", stripped)
        is_table_row = stripped.startswith("|")
        
        if (is_list_item or is_table_row) and i > 0:
            prev_line = formatted_lines[-1].strip()
            # If the previous line is not empty and is not itself a list/table item, add a blank line
            if prev_line and not prev_line.startswith("* ") and not prev_line.startswith("- ") and not re.match(r"^\d+\.\s", prev_line) and not prev_line.startswith("|"):
                formatted_lines.append("")
                
        formatted_lines.append(line)
        
    return "\n".join(formatted_lines)

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
async def get_home(request: Request):
    """
    Serves the landing page dashboard.
    """
    return templates.TemplateResponse(request=request, name="home.html")

@app.get("/home", response_class=HTMLResponse)
async def get_home_alias(request: Request):
    """
    Serves the landing page dashboard (alias /home).
    """
    return templates.TemplateResponse(request=request, name="home.html")

@app.get("/consult", response_class=HTMLResponse)
async def get_consult(request: Request):
    """
    Serves the consultation session page.
    """
    return templates.TemplateResponse(request=request, name="consult.html")

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
        MODEL_ORDER = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"]

        # Initialize session chat object if not exists
        if session_id not in chat_sessions:
            chat_sessions[session_id] = {
                "model_index": 0,
                "uploaded_files": [],
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
        
        max_retries = 2
        retry_delay = 2.0  # seconds
        
        while True:
            current_model_name = MODEL_ORDER[session["model_index"]]
            try:
                # Send message to Gemini
                response = session["chat"].send_message(message_content)
                raw_text = response.text
                break  # Success!
            except Exception as e:
                error_str = str(e)
                print(f"Error calling {current_model_name}: {error_str}")
                
                # Check for rate-limiting (429) or high demand (503)
                if "429" in error_str or "503" in error_str:
                    # Case A: Try next fallback model in sequence
                    if session["model_index"] < len(MODEL_ORDER) - 1:
                        next_index = session["model_index"] + 1
                        next_model_name = MODEL_ORDER[next_index]
                        print(f"Gemini model {current_model_name} rate-limited/unavailable. Falling back to {next_model_name} for session {session_id}...")
                        try:
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
                            continue
                        except Exception as ex:
                            print(f"Fallback setup to {next_model_name} failed: {ex}")
                            raise e
                    
                    # Case B: On last model, perform backoff sleep retry
                    if max_retries > 0:
                        print(f"No more fallback models. Sleeping for {retry_delay}s before retrying {current_model_name} (retries left: {max_retries})...")
                        time.sleep(retry_delay)
                        max_retries -= 1
                        continue
                        
                raise e
        
        # Convert raw text to HTML for presentation
        sanitized_text = sanitize_markdown(raw_text)
        display_html = markdown.markdown(sanitized_text, extensions=['tables', 'fenced_code'])
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
        # Delete all tracked uploaded files from Gemini cloud storage
        for file_name in chat_sessions[session_id].get("uploaded_files", []):
            try:
                print(f"Deleting file reference from Gemini: {file_name}")
                client.files.delete(name=file_name)
            except Exception as e:
                print(f"Failed to delete file {file_name} from Gemini: {e}")
        del chat_sessions[session_id]
        return {"status": "success", "message": f"Session {session_id} successfully cleared"}
    return {"status": "success", "message": f"Session {session_id} not active"}

@app.post("/api/upload")
async def upload_endpoint(
    session_id: str = Form(...),
    message: str = Form(""),
    file: UploadFile = File(...)
):
    """
    Accepts PDF file upload, stores it temporarily, uploads it to Gemini via the Files API,
    sends it to the multi-turn session chat, cleans up, and returns display HTML and TTS speech text.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save to a temporary file
    temp_dir = "/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, f"{session_id}_{file.filename}")

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Upload file to Gemini GenAI Files storage
        print(f"Uploading file {temp_file_path} to Gemini...")
        uploaded_file = client.files.upload(file=temp_file_path)
        print(f"File uploaded successfully to Gemini: {uploaded_file.name}")

        MODEL_ORDER = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"]

        if session_id not in chat_sessions:
            chat_sessions[session_id] = {
                "model_index": 0,
                "uploaded_files": [],
                "chat": client.chats.create(
                    model=MODEL_ORDER[0],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.7,
                    )
                )
            }

        session = chat_sessions[session_id]
        session["uploaded_files"].append(uploaded_file.name)
        response = None
        prompt_message = message.strip() if message.strip() else "Please analyze this PDF report."

        # Wait until the file is active in Gemini
        # (Though PDF files are typically processed immediately, let's wait up to 10 seconds just in case)
        wait_seconds = 0
        while uploaded_file.state.name == "PROCESSING" and wait_seconds < 10:
            print("Waiting for file to finish processing in Gemini...")
            time.sleep(1)
            wait_seconds += 1
            uploaded_file = client.files.get(name=uploaded_file.name)

        while True:
            current_model_name = MODEL_ORDER[session["model_index"]]
            try:
                # Send the uploaded file reference and the prompt message as content list
                response = session["chat"].send_message([uploaded_file, prompt_message])
                raw_text = response.text
                break
            except Exception as e:
                error_str = str(e)
                print(f"Error calling model {current_model_name} with file upload: {error_str}")
                
                # Check rate limits or retry triggers
                if "429" in error_str or "503" in error_str:
                    if session["model_index"] < len(MODEL_ORDER) - 1:
                        next_index = session["model_index"] + 1
                        next_model_name = MODEL_ORDER[next_index]
                        print(f"Falling back to {next_model_name} for file session {session_id}...")
                        try:
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
                            continue
                        except Exception as ex:
                            print(f"Fallback to {next_model_name} failed: {ex}")
                            raise e
                raise e

        # Cleanup local file, keeping the GenAI cloud file reference active for active session history
        try:
            os.remove(temp_file_path)
        except Exception as local_err:
            print(f"Failed to remove local temporary file: {local_err}")

        # Post-process response to HTML and speech text
        sanitized_text = sanitize_markdown(raw_text)
        display_html = markdown.markdown(sanitized_text, extensions=['tables', 'fenced_code'])
        tts_text = clean_text_for_tts(raw_text)

        return JSONResponse({
            "response_html": display_html,
            "tts_text": tts_text
        })

    except Exception as e:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except:
                pass
        print(f"Upload and analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"File analysis failed: {str(e)}")

# In-memory facts cache structure
facts_cache = {
    "timestamp": 0.0,
    "data": []
}

@app.get("/api/facts")
async def get_facts():
    """
    Returns 5 interesting, scientifically accurate health facts dynamically generated by Gemini
    and keyworded for dynamic image retrieval from LoremFlickr.
    """
    current_time = time.time()
    # Cache for 24 hours (86400 seconds)
    if facts_cache["data"] and (current_time - facts_cache["timestamp"] < 86400):
        return facts_cache["data"]
        
    prompt = (
        "Generate exactly 5 interesting, scientifically accurate, surprising 'Did you know?' facts strictly about human health, medicine, wellness, healthy living, physiology, or nutrition. DO NOT return general knowledge, general science, or general history trivia. Every fact must be directly and explicitly related to human health and medical wellness.\n"
        "Format the response using the provided schema. For each entry, provide the 'fact' text and a simple, one-word, lowercase English 'keyword' that represents the health topic (e.g. 'laugh', 'heart', 'water', 'forest', 'sleep', 'apple', 'run', 'fruit') for image search."
    )
    
    # Four-model fallback list
    MODEL_ORDER = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"]
    model_index = 0
    max_retries = 2
    retry_delay = 2.0
    
    raw_response_text = ""
    while True:
        model_name = MODEL_ORDER[model_index]
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=FactsResponse,
                    temperature=0.8,
                )
            )
            raw_response_text = response.text
            break
        except Exception as e:
            error_str = str(e)
            print(f"Error generating facts with {model_name}: {error_str}")
            if "429" in error_str or "503" in error_str:
                if model_index < len(MODEL_ORDER) - 1:
                    model_index += 1
                    continue
                if max_retries > 0:
                    time.sleep(retry_delay)
                    max_retries -= 1
                    continue
            
            # If all fail, return static backup facts to prevent crash!
            print("All models failed for facts generation. Returning high-quality fallback facts.")
            backup_data = [
                {"fact": "Did you know? Laughing 100 times is equivalent to 15 minutes of exercise on a stationary bicycle!", "keyword": "laugh"},
                {"fact": "Did you know? The human heart beats about 100,000 times a day, pumping around 2,000 gallons of blood!", "keyword": "heart"},
                {"fact": "Did you know? Drinking enough water boosts your brainpower, as your brain is 73% water!", "keyword": "water"},
                {"fact": "Did you know? Walking in nature reduces stress hormones and boosts your immune system by 50!", "keyword": "forest"},
                {"fact": "Did you know? Getting 7-8 hours of sleep helps consolidate memories and repairs cellular tissue!", "keyword": "sleep"}
            ]
            facts_cache["data"] = backup_data
            facts_cache["timestamp"] = current_time
            return backup_data
            
    try:
        import json
        parsed = json.loads(raw_response_text)
        entries = []
        if isinstance(parsed, dict) and "entries" in parsed:
            entries = parsed["entries"]
        elif isinstance(parsed, list):
            entries = parsed
        else:
            raise ValueError("Unknown schema structure returned")
            
        facts_cache["data"] = entries
        facts_cache["timestamp"] = current_time
        return entries
    except Exception as e:
        print(f"Failed to parse dynamically generated facts: {e}. Raw response: {raw_response_text}")
        backup_data = [
            {"fact": "Did you know? Laughing 100 times is equivalent to 15 minutes of exercise on a stationary bicycle!", "keyword": "laugh"},
            {"fact": "Did you know? The human heart beats about 100,000 times a day, pumping around 2,000 gallons of blood!", "keyword": "heart"},
            {"fact": "Did you know? Drinking enough water boosts your brainpower, as your brain is 73% water!", "keyword": "water"},
            {"fact": "Did you know? Walking in nature reduces stress hormones and boosts your immune system by 50!", "keyword": "forest"},
            {"fact": "Did you know? Getting 7-8 hours of sleep helps consolidate memories and repairs cellular tissue!", "keyword": "sleep"}
        ]
        facts_cache["data"] = backup_data
        facts_cache["timestamp"] = current_time
        return backup_data

@app.post("/api/upload-image")
async def upload_image_endpoint(
    session_id: str = Form(...),
    message: str = Form("Please analyze this photo."),
    file: UploadFile = File(...)
):
    """
    Accepts captured image upload, converts it to bytes, sends it to the Gemini session,
    and returns display HTML and TTS speech text.
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are supported")

    try:
        # Read image bytes
        image_bytes = await file.read()

        MODEL_ORDER = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"]

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
        prompt_message = message.strip() if message.strip() else "Please analyze this image."

        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=file.content_type
        )

        while True:
            current_model_name = MODEL_ORDER[session["model_index"]]
            try:
                response = session["chat"].send_message([image_part, prompt_message])
                raw_text = response.text
                break
            except Exception as e:
                error_str = str(e)
                print(f"Error calling model {current_model_name} with image upload: {error_str}")
                
                # Check rate limits or retry triggers
                if "429" in error_str or "503" in error_str:
                    if session["model_index"] < len(MODEL_ORDER) - 1:
                        next_index = session["model_index"] + 1
                        next_model_name = MODEL_ORDER[next_index]
                        print(f"Falling back to {next_model_name} for image session {session_id}...")
                        try:
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
                            continue
                        except Exception as ex:
                            print(f"Fallback to {next_model_name} failed: {ex}")
                            raise e
                raise e

        # Convert raw text to HTML for presentation
        sanitized_text = sanitize_markdown(raw_text)
        display_html = markdown.markdown(sanitized_text, extensions=['tables', 'fenced_code'])
        # Convert raw text to clean speech synthesis structure
        tts_text = clean_text_for_tts(raw_text)

        return {
            "tts_text": tts_text,
            "display_html": display_html
        }

    except Exception as e:
        print(f"Error handling image chat request for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

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
