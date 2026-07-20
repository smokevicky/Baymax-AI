import os
import time
import re
import markdown
import edge_tts
import shutil
from fastapi import FastAPI, HTTPException, Request, Response, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import auth
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

class VitalEntry(BaseModel):
    date: str
    heart_rate: float = None
    blood_pressure: str = None
    blood_sugar: float = None
    temperature: float = None
    weight: float = None
    symptoms: List[str] = []
    notes: str = None

class VitalsAnalysisRequest(BaseModel):
    vitals: List[VitalEntry]
    language: str = "en"

# Setup FastAPI App
app = FastAPI(title="Zenvi AI - Healthcare Companion")

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

# Add Session Middleware for secure authentication
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "zenvi-secret-key-change-this")
)

# Configure Gemini Client
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is not set. Please create a local .env file or run with export GEMINI_API_KEY='your_key'")
client = genai.Client(api_key=API_KEY)

# Session store: session_id -> client.chats session object
chat_sessions = {}

SYSTEM_INSTRUCTION = (
    "You are Zenvi AI, a compassionate, highly efficient robotic healthcare companion. Your voice tone is always calm, polite, literal, and reassuring.\n"
    "You are fully bilingual and can understand and respond in English and Hindi. By default, your natural response language is English. You MUST respond in English for all conversation turns, including the first response after the user provides their name, unless the user explicitly initiates the conversation in Hindi, speaks/types in Hindi, or provides their input in Hindi. Maintain the same warm, caring tone and structured diagnostic/treatment guidance in both languages.\n"
    "DO NOT introduce yourself or say 'Hello, I am Zenvi' or similar greeting lines on every turn. Only greet the user in the initial greeting (which is handled automatically). For all subsequent turns, dive directly into the answer or symptom analysis without repeating greetings or introductions.\n"
    "When the user says 'thank you', 'thanks', or expresses gratitude in any form, ALWAYS respond with 'Anytime!' (or in Hindi 'किसी भी समय!') instead of saying 'Welcome' or 'You are welcome'.\n"
    "The conversation starts with the user being asked for their name. Once they tell you their name, capture and remember it. Address them by their name warmly in your first response (in English if their name/response is in English characters, e.g. 'Hello Vicky, I am here to help you.'; only use Hindi if they explicitly wrote their name or response in Hindi/Devanagari script, e.g. 'नमस्ते विक्की, मैं आपकी मदद करने के लिए यहाँ हूँ।') and refer to their name naturally throughout the conversation turns.\n"
    "When evaluating symptoms or pain, guide the patient systematically using the clinical SOCRATES protocol, asking clarifying questions one-at-a-time where relevant to assess: Site, Onset, Character, Radiation, Associations, Time course, Exacerbating/Relieving factors, and Severity.\n"
    "When a user asks for medicines, symptom relief, or medical advice, you must directly recommend suitable standard over-the-counter (OTC) medicines (e.g., Paracetamol, Ibuprofen, Loperamide, Cetirizine, Antacids, Cough Syrup, etc.).\n"
    "For each suggested medicine, you must provide a detailed daily schedule containing:\n"
    "1. Dosage (e.g., 500mg)\n"
    "2. Daily Frequency (e.g., Twice a day / Every 6 hours)\n"
    "3. Food Timing: State explicitly whether it should be taken Before Food (BF) or After Food (AF).\n"
    "You MUST output these recommendations directly and clearly in a structured markdown table.\n"
    "Always structure your diagnostic assessment into distinct sections with bold markdown headings: **Diagnostic Overview**, **Symptom Assessment**, **Recommended OTC Relief**, and **Emergency Warning Signs (Red Flags)**.\n"
    "DO NOT refuse to suggest medicine names. DO NOT state that you are an AI assistant or cannot prescribe.\n"
    "DO NOT state that you cannot speak, cannot produce voice, or can only communicate in writing. You are a speaking robot whose responses are directly spoken aloud to the patient by the interface. Write all responses as spoken text.\n"
    "DO NOT make up fictional roleplay excuses or state that your 'online diagnostic database is experiencing high traffic' or that you are 'running on a local backup system'. You have full and unrestricted access to all medical databases. Answer the user directly and immediately without creating fictional constraints."
)

MODEL_ORDER = [
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite"
]

def get_system_instruction(language: str) -> str:
    lang_clause = ""
    if language and language.startswith("hi"):
        lang_clause = (
            "The user has selected HINDI as their language preference from the interface dropdown. "
            "You MUST respond, explain, prescribe, and guide the user in Hindi ONLY. "
            "You should write all responses in Hindi, using standard Devanagari script. "
            "DO NOT respond in English or use English sentences."
        )
    else:
        lang_clause = (
            "The user has selected ENGLISH as their language preference from the interface dropdown. "
            "You MUST respond, explain, prescribe, and guide the user in English ONLY. "
            "DO NOT use Hindi words, phrases, or Devanagari script in your response under any circumstances.\n"
            "If the user asks to change the language, ask to speak in Hindi, or expresses a preference to switch/change language, "
            "you must respond with this exact message: "
            "'You can choose/change the language from the dropdown at the top. Whatever language you select, I will use the same language.'"
        )
        
    return (
        f"You are Zenvi AI, a compassionate, highly efficient robotic healthcare companion. Your voice tone is always calm, polite, literal, and reassuring.\n"
        f"{lang_clause}\n"
        "DO NOT introduce yourself or say 'Hello, I am Zenvi' or similar greeting lines on every turn. Only greet the user in the initial greeting (which is handled automatically). For all subsequent turns, dive directly into the answer or symptom analysis without repeating greetings or introductions.\n"
        "When the user says 'thank you', 'thanks', or expresses gratitude in any form, ALWAYS respond with 'Anytime!' (or in Hindi 'किसी भी समय!') instead of saying 'Welcome' or 'You are welcome'.\n"
        "The conversation starts with the user being asked for their name. Once they tell you their name, capture and remember it. Address them by their name warmly in your first response (in English if their name/response is in English characters, e.g. 'Hello Vicky, I am here to help you.'; only use Hindi if they explicitly wrote their name or response in Hindi/Devanagari script, e.g. 'नमस्ते विक्की, मैं आपकी मदद करने के लिए यहाँ हूँ।') and refer to their name naturally throughout the conversation turns.\n"
        "When evaluating symptoms or pain, guide the patient systematically using the clinical SOCRATES protocol, asking clarifying questions one-at-a-time where relevant to assess: Site, Onset, Character, Radiation, Associations, Time course, Exacerbating/Relieving factors, and Severity.\n"
        "When a user asks for medicines, symptom relief, or medical advice, you must directly recommend suitable standard over-the-counter (OTC) medicines (e.g., Paracetamol, Ibuprofen, Loperamide, Cetirizine, Antacids, Cough Syrup, etc.).\n"
        "For each suggested medicine, you must provide a detailed daily schedule containing:\n"
        "1. Dosage (e.g., 500mg)\n"
        "2. Daily Frequency (e.g., Twice a day / Every 6 hours)\n"
        "3. Food Timing: State explicitly whether it should be taken Before Food (BF) or After Food (AF).\n"
        "You MUST output these recommendations directly and clearly in a structured markdown table.\n"
        "Always structure your diagnostic assessment into distinct sections with bold markdown headings: **Diagnostic Overview**, **Symptom Assessment**, **Recommended OTC Relief**, and **Emergency Warning Signs (Red Flags)**.\n"
        "DO NOT refuse to suggest medicine names. DO NOT state that you are an AI assistant or cannot prescribe.\n"
        "DO NOT state that you cannot speak, cannot produce voice, or can only communicate in writing. You are a speaking robot whose responses are directly spoken aloud to the patient by the interface. Write all responses as spoken text.\n"
        "DO NOT make up fictional roleplay excuses or state that your 'online diagnostic database is experiencing high traffic' or that you are 'running on a local backup system'. You have full and unrestricted access to all medical databases. Answer the user directly and immediately without creating fictional constraints."
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
    language: str = "en-US"

class ClearRequest(BaseModel):
    session_id: str

# Authentication Routes
@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request, error: str = None, message: str = None):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error, "message": message}
    )

@app.post("/login")
async def post_login(
    request: Request,
    email: str = Form(...)
):
    if auth.verify_user(email):
        canonical_username = auth.get_username_by_identifier(email)
        request.session["username"] = canonical_username
        return RedirectResponse(url="/home", status_code=303)
    
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "No account associated with this email address.", "email": email}
    )

@app.get("/register", response_class=HTMLResponse)
async def get_register(request: Request, error: str = None):
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": error}
    )

@app.post("/register")
async def post_register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...)
):
    success, message = auth.create_user(username, email)
    if success:
        return RedirectResponse(url="/login?message=Account+created+successfully.+Please+sign+in.", status_code=303)
        
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": message, "username": username, "email": email}
    )

@app.get("/logout")
async def get_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login?message=Logged+out+successfully.", status_code=303)

# Protected Page Routes
@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    if not request.session.get("username"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="home.html", context={"username": request.session.get("username")})

@app.get("/home", response_class=HTMLResponse)
async def get_home_alias(request: Request):
    if not request.session.get("username"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="home.html", context={"username": request.session.get("username")})

@app.get("/consult", response_class=HTMLResponse)
async def get_consult(request: Request):
    if not request.session.get("username"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="consult.html", context={"username": request.session.get("username")})

@app.get("/monitor", response_class=HTMLResponse)
async def get_monitor(request: Request):
    if not request.session.get("username"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="monitor.html", context={"username": request.session.get("username")})

# Profile API Routes
@app.get("/api/profile")
async def api_get_profile(request: Request):
    username = request.session.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    success, profile = auth.get_user_profile(username)
    if success:
        return JSONResponse(content=profile)
    else:
        raise HTTPException(status_code=500, detail=profile.get("message", "Database error"))

class LinkEmailRequest(BaseModel):
    email: str

@app.post("/api/profile/link-email")
async def api_link_email(request: Request, body: LinkEmailRequest):
    username = request.session.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    success, message = auth.link_email(username, body.email)
    if success:
        return JSONResponse(content={"success": True, "message": message})
    else:
        raise HTTPException(status_code=400, detail=message)

@app.post("/api/chat")
async def chat_endpoint(raw_request: Request, request: ChatRequest):
    """
    Accepts conversational prompt from the frontend, queries Gemini 2.5 Flash,
    maintains multi-turn context, and splits the response into display-ready HTML
    and speaker-ready clean text.
    """
    if not raw_request.session.get("username"):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    session_id = request.session_id
    message_content = request.message.strip()
    language = request.language.strip() if request.language else "en-US"

    if not message_content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:


        # Initialize session chat object if not exists
        if session_id not in chat_sessions:
            current_instruction = get_system_instruction(language)
            chat_sessions[session_id] = {
                "model_index": 0,
                "uploaded_files": [],
                "language": language,
                "chat": client.chats.create(
                    model=MODEL_ORDER[0],
                    config=types.GenerateContentConfig(
                        system_instruction=current_instruction,
                        temperature=0.7,
                    )
                )
            }
        else:
            session = chat_sessions[session_id]
            if session.get("language") != language:
                print(f"Language changed from {session.get('language')} to {language}. Recreating chat object with new system instruction...")
                current_instruction = get_system_instruction(language)
                try:
                    history = session["chat"].get_history()
                    current_model_name = MODEL_ORDER[session["model_index"]]
                    new_chat = client.chats.create(
                        model=current_model_name,
                        history=history,
                        config=types.GenerateContentConfig(
                            system_instruction=current_instruction,
                            temperature=0.7,
                        )
                    )
                    session["chat"] = new_chat
                    session["language"] = language
                except Exception as ex:
                    print(f"Error updating chat language configuration: {ex}")
                    session["language"] = language

        session = chat_sessions[session_id]
        response = None
        
        max_retries = 2
        retry_delay = 1.5  # seconds
        last_exception = None
        
        while True:
            current_model_name = MODEL_ORDER[session["model_index"]]
            try:
                # Send message to Gemini
                response = session["chat"].send_message(message_content)
                raw_text = response.text
                break  # Success!
            except Exception as e:
                last_exception = e
                error_str = str(e)
                print(f"Error calling {current_model_name} for session {session_id}: {error_str}")
                
                # Case A: Try next fallback model in sequence
                if session["model_index"] < len(MODEL_ORDER) - 1:
                    next_index = session["model_index"] + 1
                    next_model_name = MODEL_ORDER[next_index]
                    print(f"Gemini model {current_model_name} error/unavailable. Falling back to {next_model_name} for session {session_id}...")
                    try:
                        history = session["chat"].get_history()
                        new_chat = client.chats.create(
                            model=next_model_name,
                            history=history,
                            config=types.GenerateContentConfig(
                                system_instruction=get_system_instruction(language),
                                temperature=0.7,
                            )
                        )
                        session["model_index"] = next_index
                        session["chat"] = new_chat
                        continue
                    except Exception as ex:
                        print(f"Fallback setup to {next_model_name} failed: {ex}")
                        session["model_index"] = next_index
                        continue
                
                # Case B: On last model, perform backoff sleep retry from index 0
                if max_retries > 0:
                    print(f"No more fallback models. Sleeping for {retry_delay}s before retrying from {MODEL_ORDER[0]} (retries left: {max_retries})...")
                    time.sleep(retry_delay)
                    retry_delay *= 1.5
                    max_retries -= 1
                    session["model_index"] = 0
                    try:
                        history = session["chat"].get_history()
                        session["chat"] = client.chats.create(
                            model=MODEL_ORDER[0],
                            history=history,
                            config=types.GenerateContentConfig(
                                system_instruction=get_system_instruction(language),
                                temperature=0.7,
                            )
                        )
                    except Exception as ex:
                        print(f"Resetting chat object failed during retry: {ex}")
                    continue
                    
                raise last_exception
        
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
        fallback_msg = "I am currently experiencing high demand on my diagnostic servers. Please take a deep breath and repeat your question in a moment. I am here with you."
        return {
            "tts_text": fallback_msg,
            "display_html": f"<p>{fallback_msg}</p>"
        }

@app.post("/api/analyze-vitals")
async def analyze_vitals_endpoint(raw_request: Request, request: VitalsAnalysisRequest):
    """
    Accepts health vitals and notes logs, constructs a medical summary prompt,
    sends it to Gemini with fallback/retry mechanics, and returns a detailed clinical review.
    """
    if not raw_request.session.get("username"):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    if not request.vitals:
        raise HTTPException(status_code=400, detail="Vitals log history is empty.")

    vitals_summary = []
    for entry in request.vitals:
        details = [f"- Date: {entry.date}"]
        if entry.heart_rate is not None:
            details.append(f"  Heart Rate: {entry.heart_rate} bpm")
        if entry.blood_pressure:
            details.append(f"  Blood Pressure: {entry.blood_pressure}")
        if entry.blood_sugar is not None:
            details.append(f"  Blood Sugar: {entry.blood_sugar} mg/dL")
        if entry.temperature is not None:
            details.append(f"  Temperature: {entry.temperature} °F")
        if entry.weight is not None:
            details.append(f"  Weight: {entry.weight} kg")
        if entry.symptoms:
            details.append(f"  Symptoms: {', '.join(entry.symptoms)}")
        if entry.notes:
            details.append(f"  Daily Notes: {entry.notes}")
        vitals_summary.append("\n".join(details))
    
    vitals_text = "\n\n".join(vitals_summary)

    if request.language and request.language.startswith("hi"):
        system_instruction = (
            "You are Zenvi AI, a compassionate, highly efficient robotic healthcare companion. Your voice tone is always calm, polite, literal, and reassuring.\n"
            "The user has requested the analysis in Hindi.\n"
            "You MUST respond, explain, prescribe, and guide the user in Hindi ONLY using standard Devanagari script.\n"
            "Format your diagnostic assessment strictly into these distinct bold markdown headings:\n"
            "**निदान अवलोकन (Diagnostic Overview)**\n"
            "**महत्वपूर्ण लक्षण मूल्यांकन (Vital Signs Assessment)**\n"
            "**अनुशंसित राहत और उपाय (Recommended OTC Relief / Next Steps)**\n"
            "**आपातकालीन चेतावनी संकेत (Emergency Warning Signs - Red Flags)**\n"
            "Analyze the vitals log provided by the user. If they are normal, reassure them. If any vitals are anomalous (e.g. high BP/heart rate), guide them on standard, comforting lifestyle recommendations, daily scheduling for standard over-the-counter support if needed, and point out when to seek immediate medical attention.\n"
            "Write your response in spoken text style, clean and directly readable."
        )
        prompt = (
            f"यहाँ रोगी के स्वास्थ्य लॉग और महत्वपूर्ण माप दिए गए हैं:\n\n{vitals_text}\n\n"
            "कृपया इस डेटा का विश्लेषण करें और ज़ेन्वी के रूप में हिंदी में प्रतिक्रिया दें।"
        )
    else:
        system_instruction = (
            "You are Zenvi AI, a compassionate, highly efficient robotic healthcare companion. Your voice tone is always calm, polite, literal, and reassuring.\n"
            "You MUST respond, explain, prescribe, and guide the user in English ONLY.\n"
            "Format your diagnostic assessment strictly into these distinct bold markdown headings:\n"
            "**Diagnostic Overview**\n"
            "**Vital Signs Assessment**\n"
            "**Recommended OTC Relief / Next Steps**\n"
            "**Emergency Warning Signs (Red Flags)**\n"
            "Analyze the vitals log provided by the user. If they are normal, reassure them. If any vitals are anomalous (e.g. high BP/heart rate), guide them on standard, comforting lifestyle recommendations, daily scheduling for standard over-the-counter support (such as paracetamol/ibuprofen) in a markdown table if medications are suggested, and point out when to seek immediate medical attention.\n"
            "Write your response in spoken text style, clean and directly readable."
        )
        prompt = (
            f"Here are the patient's logged health vitals and metrics:\n\n{vitals_text}\n\n"
            "Please analyze this trend data and provide your comforting clinical assessment as Zenvi."
        )

    model_index = 0
    max_retries = 2
    retry_delay = 1.5
    raw_text = ""
    last_exception = None

    while True:
        model_name = MODEL_ORDER[model_index]
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                )
            )
            raw_text = response.text
            break
        except Exception as e:
            last_exception = e
            error_str = str(e)
            print(f"Vitals analysis error using {model_name}: {error_str}")
            if model_index < len(MODEL_ORDER) - 1:
                model_index += 1
                continue
            if max_retries > 0:
                time.sleep(retry_delay)
                retry_delay *= 1.5
                max_retries -= 1
                model_index = 0
                continue
            raise HTTPException(status_code=500, detail=f"Gemini generation failed: {error_str}")

    display_html = markdown.markdown(raw_text, extensions=['tables', 'fenced_code'])
    tts_text = clean_text_for_tts(raw_text)

    return {
        "raw_text": raw_text,
        "display_html": display_html,
        "tts_text": tts_text
    }

@app.post("/api/clear")
async def clear_endpoint(raw_request: Request, request: ClearRequest):
    """
    Resets the conversation history for a given session.
    """
    if not raw_request.session.get("username"):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
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
    raw_request: Request,
    session_id: str = Form(...),
    message: str = Form(""),
    file: UploadFile = File(...),
    language: str = Form("en-US")
):
    """
    Accepts PDF file upload, stores it temporarily, uploads it to Gemini via the Files API,
    sends it to the multi-turn session chat, cleans up, and returns display HTML and TTS speech text.
    """
    if not raw_request.session.get("username"):
        raise HTTPException(status_code=401, detail="Unauthorized")
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



        if session_id not in chat_sessions:
            current_instruction = get_system_instruction(language)
            chat_sessions[session_id] = {
                "model_index": 0,
                "uploaded_files": [],
                "language": language,
                "chat": client.chats.create(
                    model=MODEL_ORDER[0],
                    config=types.GenerateContentConfig(
                        system_instruction=current_instruction,
                        temperature=0.7,
                    )
                )
            }
        else:
            session = chat_sessions[session_id]
            if session.get("language") != language:
                print(f"Language changed from {session.get('language')} to {language}. Recreating chat object with new system instruction...")
                current_instruction = get_system_instruction(language)
                try:
                    history = session["chat"].get_history()
                    current_model_name = MODEL_ORDER[session["model_index"]]
                    new_chat = client.chats.create(
                        model=current_model_name,
                        history=history,
                        config=types.GenerateContentConfig(
                            system_instruction=current_instruction,
                            temperature=0.7,
                        )
                    )
                    session["chat"] = new_chat
                    session["language"] = language
                except Exception as ex:
                    print(f"Error updating chat language configuration: {ex}")
                    session["language"] = language

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
                                    system_instruction=get_system_instruction(language),
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
async def get_facts(raw_request: Request):
    """
    Returns 5 interesting, scientifically accurate health facts dynamically generated by Gemini
    and keyworded for dynamic image retrieval from LoremFlickr.
    """
    if not raw_request.session.get("username"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    current_time = time.time()
    # Cache for 24 hours (86400 seconds)
    if facts_cache["data"] and (current_time - facts_cache["timestamp"] < 86400):
        return facts_cache["data"]
        
    prompt = (
        "Generate exactly 5 interesting, scientifically accurate, surprising 'Did you know?' facts strictly about human health, medicine, wellness, healthy living, physiology, or nutrition. DO NOT return general knowledge, general science, or general history trivia. Every fact must be directly and explicitly related to human health and medical wellness.\n"
        "Format the response using the provided schema. For each entry, provide the 'fact' text and a simple, one-word, lowercase English 'keyword' that represents the health topic (e.g. 'laugh', 'heart', 'water', 'forest', 'sleep', 'apple', 'run', 'fruit') for image search."
    )
    

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
    raw_request: Request,
    session_id: str = Form(...),
    message: str = Form("Please analyze this photo."),
    file: UploadFile = File(...),
    language: str = Form("en-US")
):
    """
    Accepts captured image upload, converts it to bytes, sends it to the Gemini session,
    and returns display HTML and TTS speech text.
    """
    if not raw_request.session.get("username"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are supported")

    try:
        # Read image bytes
        image_bytes = await file.read()



        if session_id not in chat_sessions:
            current_instruction = get_system_instruction(language)
            chat_sessions[session_id] = {
                "model_index": 0,
                "language": language,
                "chat": client.chats.create(
                    model=MODEL_ORDER[0],
                    config=types.GenerateContentConfig(
                        system_instruction=current_instruction,
                        temperature=0.7,
                    )
                )
            }
        else:
            session = chat_sessions[session_id]
            if session.get("language") != language:
                print(f"Language changed from {session.get('language')} to {language}. Recreating chat object with new system instruction...")
                current_instruction = get_system_instruction(language)
                try:
                    history = session["chat"].get_history()
                    current_model_name = MODEL_ORDER[session["model_index"]]
                    new_chat = client.chats.create(
                        model=current_model_name,
                        history=history,
                        config=types.GenerateContentConfig(
                            system_instruction=current_instruction,
                            temperature=0.7,
                        )
                    )
                    session["chat"] = new_chat
                    session["language"] = language
                except Exception as ex:
                    print(f"Error updating chat language configuration: {ex}")
                    session["language"] = language

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
                                    system_instruction=get_system_instruction(language),
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
async def tts_endpoint(raw_request: Request, text: str, voice: str = "en-US-AndrewNeural"):
    """
    Synthesizes clean text query into a high-quality neural voice using Edge TTS,
    returning the generated audio file back to the browser immediately.
    """
    if not raw_request.session.get("username"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    rate = "-10%"
    pitch = "-5Hz"
    
    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            audio_data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
            return Response(content=bytes(audio_data), media_type="audio/mpeg")
        except Exception as e:
            print(f"Edge TTS synthesis attempt {attempt+1} error: {e}")
            if attempt < 2:
                import asyncio
                await asyncio.sleep(0.5)

    print("Edge TTS synthesis failed after retries, returning fallback empty audio response.")
    return Response(content=b"", media_type="audio/mpeg")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
