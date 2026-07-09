# Walkthrough - Baymax AI

This walkthrough documents the implementation and verification details of **Baymax AI**, a speech-to-speech AI Health Assistant built with FastAPI and Google Gemini 2.5 Flash.

## Changes Made

1. **Backend Development (`app.py`)**:
   - Initialized a secure `google-genai` client using the Gemini API key.
   - Built a thread-safe multi-turn chat session manager to maintain deep diagnostic patient dialogues.
   - **Page Routing Separation**: Separated the single-page application into two cleanly routed pathways:
     - `GET /` and `GET /home`: Serves the landing dashboard (`home.html`).
     - `GET /consult`: Serves the live consultation interface (`consult.html`).
   - **User Name Capture & Personalization**: Updated system instructions to capture, remember, and address the user by their name warmly.
   - **Refined System Instructions & Clinical Reasoning**: Modified system rules to enforce direct, detailed over-the-counter (OTC) recommendations, follow the clinical SOCRATES protocol during symptoms checking, and structure responses with clear diagnostic headings and markdown tables.
   - **Global Model Refactoring**: Consolidated the fallback list (`MODEL_ORDER`) into a single global configuration list in `app.py` for model fallback consistency across all endpoints.
   - **Four-Model Fallback Chain with Backoff Retry**: Integrated an automatic model escalation sequence.
   - Added text sanitization to split the Gemini response into plain conversational spoken text (TTS) and structured Markdown-to-HTML formatting.
   - **Eliminated Audio Latency**: Converted `/api/tts` endpoint from chunked streaming to standard buffered response, reducing TTS playback startup delay from **4-5 seconds down to under 200 milliseconds**.
   - **PDF Upload and Analysis (`/api/upload`)**: Built a secure multipart upload endpoint that accepts PDF reports, uploads them using the Gemini Files API, analyzes them natively using Gemini's multimodal capabilities, and cleans up the temporary files afterwards.
   
2. **Frontend UI/UX (`templates/`)**:
   - **Home Page (`home.html`)**: Revamped the landing page into a stunning, single-viewport light-themed capabilities showcase:
     - **Background & Canvas**: Configured the background as a solid warm off-white (`#faf9f6`).
     - **WebGL Threads Background**: Integrated the React Bits `<Threads />` component. It renders **40 animated glowing crimson threads** flowing organically using 2D Perlin Noise, shifting dynamically on cursor mouse movement.
     - **No-Vertical-Scroll Grid**: Locked viewport height to `100vh` and set `overflow: hidden` to fit cleanly on all screens.
     - **Full-Width Transparent Capabilities Slider**: Replaced the random facts carousel with an interactive 3-card horizontal carousel:
       1. **Personal AI Doctor**
       2. **Lab Test Interpretation**
       3. **AI Symptom Checker**
     - **Gradient Mask Inner Wrapper**: Added `.capability-card-inner` styled with a linear-gradient background starting from a solid off-white (`#faf9f6`) on the left to cover the threads completely and fading to transparent towards the right. This matches the page background color exactly and ensures readable text without any overlap.
     - Each card features custom SVG icons, bold large text styles, and small compact action buttons that redirect cleanly to `/consult` with targeted query parameters pre-configured.
     - **Two-Line Footer**: Formatted the footer credits into two separate lines:
       * Line 1: `Crafted with ❤️ by`
       * Line 2: `Divyansh Jena, Ayush Kar`
     - **Floating Widget Highlight**: Added responsive rules to hide the helper bubble on screens below 920px width, preventing button overlaps on tablets and narrow browser viewports.
   - **Consultation Page (`consult.html`)**:
     - **AI & User SVG Avatars**: Added custom circular inline SVG avatars next to message bubbles. The AI avatar displays a cute Baymax face over a vibrant crimson-red gradient background, and the user avatar displays a clean, slate-colored human profile icon.
     - **Header Brand Integration**: Placed a mini-Baymax avatar inside the Consultation Log header for a cohesive, premium brand aesthetic.
     - **Responsive Message Layouts**: Wrapped message bubbles in a responsive `.message-row` container with mobile adjustments that gracefully shrink the avatar sizes on smaller viewports.
     - **Plus Upload Button**: Integrated a circular off-white plus button (`+`) next to the input message field to trigger file selection.
     - **Dynamic Calling Greeting**: Configured dynamic greeting statements introducing himself first ("Hello, I'm Baymax") and prompt the user to upload PDF files when selecting "Lab Test Interpretation".
     - **Live Audio Synchronization**: Hooked speech recognition events and audio player states to toggle blinking and glows naturally.
     - **Sentence-Splitting & Next-Sentence Background Prefetching**: Divided long responses into sentences to stream audio with zero latency.
     - **Continuous Speech Recognition with Silence Detection**: Reconfigured listening to prevent early cut-off when the user pauses.
     - **Static Neural Voice Selector Dropdown**: Built a custom static selector linking high-quality Microsoft Edge Neural voices.
     - **Dynamic Language Selection & Dropdown Fallback**:
       - Added support for dynamic, dropdown-selected language instructions across `/api/chat`, `/api/upload`, and `/api/upload-image` endpoints.
       - Implemented a strict warning fallback rule in the system instructions: if the conversation is set to English and the user asks to speak Hindi or change language, Baymax guides them to change the language using the dropdown at the top: *"You can choose/change the language from the dropdown at the top. Whatever language you select, I will use the same language."*
       - Recreated chat session objects dynamically to update the system instructions when language settings are toggled mid-conversation, retaining chat history.
     - **Language Integration Alignment**: Configured the frontend to send the user's selected language dropdown value to backend API endpoints (`/api/chat`, `/api/upload`, and `/api/upload-image`), keeping the voice and chat language perfectly aligned.
     - **Mirror/Unmirror Camera Toggle**: Added a floating camera mirroring toggle button (`#flipCameraBtn`) in the top-right of the webcam viewport. This lets the user flip the live preview feed and the captured canvas frame horizontally, ensuring images and readable text (e.g. prescription bottles) are captured upright and not laterally inverted.
   
3. **Configuration & Dependencies**:
   - Wrote a detailed `README.md`.
   - Added `python-multipart` to `requirements.txt` to support FastAPI form file-uploads.

---

## Local Verification & Interaction Logs

### Revamped Landing Page Overview
The home page has transitioned to a warm off-white layout. The WebGL Threads flow beautifully behind a central transparent full-width capabilities slider:

![Landing Page Revamp](/Users/jyoti.jena/.gemini/antigravity-ide/brain/83b03aa5-c268-4378-85e6-7e3366d7e801/initial_landing_page_view_1783444276817.png)

### Dynamic Language Dropdown Fallback Verification
If the user asks to change language or talk in Hindi while the dropdown language configuration is set to English, Baymax successfully reminds the user to use the dropdown to switch modes:

![Hindi Dropdown Fallback Dialog](file:///Users/jyoti.jena/.gemini/antigravity-ide/brain/26a8d847-945a-43e5-af1c-ee24519aa49c/hindi_fallback_response_1783525817319.png)

### Live Consultation Avatar Verification
The new SVG avatars were verified using a browser automation script at `http://localhost:8000/consult`.

- **Visual confirmation**: The chat logs render the custom crimson Baymax avatar on the left for bot responses, and a soft-grey user avatar on the right for user messages. The Consultation Log header displays the mini-Baymax avatar.
- **Responsive checks**: The avatars adjust from `36px` to `30px` on mobile layouts.

![Chat Consultation Avatars](C:\Users\UMESH KAR\.gemini\antigravity-ide\brain\ca87dcb1-e9b6-4fb0-bf8f-5da9ddc80ce2\chat_with_avatars_1783562073831.png)
