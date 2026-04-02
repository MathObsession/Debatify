import os
import json
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change in production

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')

def ensure_data_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    for path in [USERS_FILE, SESSIONS_FILE, HISTORY_FILE]:
        if not os.path.exists(path):
            with open(path, 'w') as f:
                json.dump([], f)

def read_json(path):
    ensure_data_files()
    with open(path, 'r') as f:
        return json.load(f)

def write_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def next_id(items):
    if not items:
        return 1
    return max(item.get('id', 0) for item in items) + 1

ensure_data_files()

# Ollama endpoint (default local)
OLLAMA_URL = "http://localhost:11434/api/generate"
# Use a model that works well with instructions, e.g., mistral, llama2, or phi3
MODEL = "qwen3-vl:235b-cloud"

@app.before_request
def require_login():
    allowed_routes = ['login', 'register', 'static', 'index']
    if request.endpoint not in allowed_routes and 'user_id' not in session:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        users = read_json(USERS_FILE)
        user = next((u for u in users if u['email'] == email), None)
        if user and user['password'] == password:
            session['user_id'] = user['id']
            session['user_email'] = user['email']
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        users = read_json(USERS_FILE)
        existing = next((u for u in users if u['email'] == email), None)
        if existing:
            flash('Email already registered')
        else:
            new_user = {'id': next_id(users), 'username': username, 'email': email, 'password': password, 'profile_pic': ''}
            users.append(new_user)
            write_json(USERS_FILE, users)
            session['user_id'] = new_user['id']
            session['user_email'] = new_user['email']
            return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_email', None)
    return redirect(url_for('index'))

# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route('/')
def index():
    """Render the landing page."""
    return render_template('landing.html')

@app.route('/modes')
def modes():
    """Render the modes selection page."""
    return render_template('modes.html')

@app.route('/duration')
def duration():
    """Render the duration selection page."""
    return render_template('duration.html')

@app.route('/topic')
def topic():
    """Render the topic selection page."""
    return render_template('topic.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users = read_json(USERS_FILE)
    user = next((u for u in users if u['id'] == session['user_id']), None)
    if not user:
        flash('User not found')
        return redirect(url_for('login'))

    all_sessions = read_json(SESSIONS_FILE)
    sessions = [s for s in all_sessions if s['user_id'] == session['user_id']]
    sessions.sort(key=lambda s: s.get('start_time', ''), reverse=True)

    total = len(sessions)
    wins = len([s for s in sessions if s.get('result') == 'win'])
    accuracy = 0 if total == 0 else int(wins / total * 100)

    # streak = consecutive days with sessions
    dates = sorted({s['start_time'].split('T')[0] for s in sessions if s.get('start_time')}, reverse=True)
    streak = 0
    from datetime import date, timedelta
    today = date.today()
    current = today
    for d in dates:
        try:
            dt = date.fromisoformat(d)
        except Exception:
            continue
        if dt == current:
            streak += 1
            current -= timedelta(days=1)
        elif dt == current - timedelta(days=1):
            streak += 1
            current -= timedelta(days=1)
        else:
            break

    return render_template('profile.html', user=user, sessions=sessions, accuracy=accuracy, streak=streak)

@app.route('/upload_profile', methods=['POST'])
def upload_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    file = request.files.get('profile_pic')
    if file:
        filename = f"p_{session['user_id']}_{int(datetime.now().timestamp())}.jpg"
        upload_dir = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        path = os.path.join(upload_dir, filename)
        file.save(path)

        users = read_json(USERS_FILE)
        for u in users:
            if u['id'] == session['user_id']:
                u['profile_pic'] = filename
                break
        write_json(USERS_FILE, users)

    return redirect(url_for('profile'))

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    all_sessions = read_json(SESSIONS_FILE)
    sessions = [s for s in all_sessions if s['user_id'] == session['user_id']]
    sessions.sort(key=lambda s: s.get('start_time', ''), reverse=True)
    return render_template('history.html', sessions=sessions)

@app.route('/generate_topic', methods=['GET'])
def generate_topic():
    """Generate a random debate topic using AI."""
    prompt = "Generate a single, interesting debate topic that is suitable for a debate. Make it concise and engaging. Just output the topic, nothing else."
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 50, "temperature": 0.8}
        })
        response.raise_for_status()
        topic = response.json()['response'].strip()
        return jsonify({"topic": topic})
    except Exception as e:
        return jsonify({"error": f"Failed to generate topic: {str(e)}"}), 500

@app.route('/get_session_info', methods=['GET'])
def get_session_info():
    """Get current session info for the debate page."""
    duration = session.get('duration', 10)
    return jsonify({"duration": duration})

@app.route('/start_session', methods=['POST'])
def start_session():
    """
    Initialize a new debate session.
    Expects JSON: { mode, duration, topic (optional) }
    """
    data = request.json
    mode = data.get('mode')
    duration = int(data.get('duration', 10))
    topic = data.get('topic', '')
    session['mode'] = mode
    session['duration'] = duration
    session['topic'] = topic
    session['history'] = []          # List of {user, ai} dicts
    session['start_time'] = datetime.now().isoformat()

    all_sessions = read_json(SESSIONS_FILE)
    new_session = {
        'id': next_id(all_sessions),
        'user_id': session['user_id'],
        'mode': mode,
        'duration': duration,
        'topic': topic,
        'start_time': session['start_time'],
        'end_time': None,
        'result': None,
        'score': 0
    }
    all_sessions.append(new_session)
    write_json(SESSIONS_FILE, all_sessions)
    session['session_id'] = new_session['id']

    return jsonify({"status": "ok"})

@app.route('/debate', methods=['GET'])
def debate_page():
    """Render the debate page."""
    return render_template('debate.html')

@app.route('/debate', methods=['POST'])
def debate():
    """
    Process user input and return AI response.
    Expects JSON: { user_text }
    """
    user_text = request.json.get('user_text', '').strip()
    if not user_text:
        return jsonify({"error": "Empty input"}), 400

    mode = session.get('mode')
    if not mode:
        return jsonify({"error": "Session not started"}), 400

    # Build prompt based on mode
    prompt = build_prompt(mode, user_text, session.get('history', []), session.get('topic', ''))

    # Call Ollama
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 150, "temperature": 0.7}
        })
        response.raise_for_status()
        ai_text = response.json()['response'].strip()
    except Exception as e:
        return jsonify({"error": f"Ollama error: {str(e)}"}), 500

    # Store in history
    history = session.get('history', [])
    history.append({"user": user_text, "ai": ai_text})
    # Keep only last 12 turns to avoid context overflow
    session['history'] = history[-12:]

    # persist history row
    if session.get('session_id'):
        all_history = read_json(HISTORY_FILE)
        all_history.append({
            'session_id': session['session_id'],
            'user_text': user_text,
            'ai_text': ai_text,
            'timestamp': datetime.now().isoformat()
        })
        write_json(HISTORY_FILE, all_history)

    return jsonify({"response": ai_text})

@app.route('/end_session', methods=['POST'])
def end_session():
    """
    End the session and return a summary (for judge/coach modes).
    """
    mode = session.get('mode')
    history = session.get('history', [])

    if mode in ['judging', 'coach']:
        summary_prompt = build_summary_prompt(mode, history, session.get('topic', ''))
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": MODEL,
                "prompt": summary_prompt,
                "stream": False,
                "options": {"num_predict": 200, "temperature": 0.5}
            })
            summary = response.json()['response'].strip()
        except Exception as e:
            summary = f"Error generating summary: {str(e)}"
    else:
        summary = "Session ended. Thanks for debating!"

    # update session result for history and keep user logged in
    if session.get('session_id'):
        all_sessions = read_json(SESSIONS_FILE)
        for s in all_sessions:
            if s['id'] == session['session_id']:
                s['end_time'] = datetime.now().isoformat()
                if mode == 'judging':
                    # extract a numeric score from AI feedback
                    import re
                    score_match = re.search(r'(\b(?:10|[1-9])\b)', summary)
                    score = int(score_match.group(1)) if score_match else 0
                    s['score'] = score
                    s['result'] = 'win' if score >= 6 else 'lose'
                else:
                    s['score'] = 0
                    s['result'] = 'completed'
                break
        write_json(SESSIONS_FILE, all_sessions)

    user_id = session.get('user_id')
    user_email = session.get('user_email')
    session_keys = ['user_id', 'user_email']
    new_session = {k: session[k] for k in session_keys if k in session}
    session.clear()
    session.update(new_session)

    # clear debate-specific session data
    for key in ['mode', 'duration', 'topic', 'history', 'start_time', 'session_id']:
        session.pop(key, None)

    return jsonify({"summary": summary})

# ----------------------------------------------------------------------
# Prompt builders
# ----------------------------------------------------------------------

def build_prompt(mode, user_text, history, topic):
    """Construct the system + conversation prompt for the LLM."""
    system_prompt = get_system_prompt(mode, topic)
    context = ""
    for turn in history[-6:]:  # last 6 turns for context
        context += f"User: {turn['user']}\nAI: {turn['ai']}\n"
    # Add current user input
    prompt = f"{system_prompt}\n\n{context}User: {user_text}\nAI:"
    return prompt

def get_system_prompt(mode, topic):
    """Return the system prompt for a given mode."""
    topic_str = f" The debate topic is '{topic}'." if topic else ""
    if mode == 'casual':
        return f"You are a casual debate partner who is like a a general speaker, your goal is to go against the user on {topic_str} topic. Do not let the user pursuade you. once you feel that it's the end and you no longer have points just accept defeat and tell the user that they win – try to avoid this"
    elif mode == 'pro':
        return f"You are a sharp, logical debate opponent. Challenge the user’s assumptions, point out logical flaws, and give strong rebuttals. Keep responses concise on{topic_str}. Once you start declare who are you with and avoid to loose at any cost"
    elif mode == 'judging':
        return f"You are a debate judge who is carefully listening to what the user is telling and giving strong oppositions on {topic_str}. Then give a score to the user based out of 10 on logic, evidence, and clarity. keep the scoring concise"
    elif mode == 'coach':
        return f"You are an expirenced debate coach who specialises in teaching debate techniques for the pase decade. You have to give strong counters to the users response on {topic_str} and then tell the user where they went wrong, give a line by line summary, is the user is discourage, encourage them."
    else:
        return "You are a helpful assistant."

def build_summary_prompt(mode, history, topic):
    """For judge/coach modes, generate a session summary."""
    # Convert history to a readable format
    transcript = "\n".join([f"User: {t['user']}\nAI: {t['ai']}" for t in history])
    if mode == 'judging':
        prompt = f"""You are a debate judge. Based on the following conversation about '{topic}', provide a final verdict: who won, and why? Also give a final score (1-10) for the user's performance. Keep it concise.

Conversation:
{transcript}

Final verdict:"""
    else:  # coach
        prompt = f"""You are a debate coach. Based on the following conversation about '{topic}', provide a summary of the user's strengths and weaknesses, and give specific advice for improvement. Keep it constructive and concise.

Conversation:
{transcript}

Feedback:"""
    return prompt

@app.before_request
def require_login():
    allowed_routes = ['login', 'register', 'static', 'index']
    if request.endpoint not in allowed_routes and 'user_id' not in session:
        return redirect(url_for('login'))

# ----------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, port=5000)