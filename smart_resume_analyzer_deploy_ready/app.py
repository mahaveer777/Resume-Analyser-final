from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os
import re

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'smart_resume_analyzer_secret_key')

# --- NLP SETUP (spaCy) ---
# spaCy adds lemmatization-aware matching so skills and action verbs are recognised
# regardless of tense, plural form, or inflection (e.g. "developing"/"developed"/
# "develops" all match "develop"; "databases" matches "database"). This replaces
# the previous exact-word regex matching with the same regex approach applied to
# lemmatized text, so it's a strictly more capable drop-in — nothing about the
# scoring formula, routes, or database changes.
#
# If spaCy or its English model isn't installed in the running environment, the
# app automatically falls back to the original plain-text matching further down
# instead of crashing, so a missing NLP model degrades matching quality rather
# than taking the whole app down.
try:
    import spacy
    try:
        # Parser and NER aren't needed for lemmatization/POS tagging, so they're
        # disabled to keep per-request analysis fast.
        nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    except OSError:
        nlp = None
except ImportError:
    nlp = None

NLP_ENABLED = nlp is not None

# Cache of skill/keyword-phrase -> lemma. The same skill keywords (e.g. "python",
# "machine learning") recur across every request and every role, so caching their
# lemmatized form avoids re-running spaCy on identical short strings repeatedly.
_phrase_lemma_cache = {}

def lemmatize_phrase(phrase):
    """Lowercased, lemmatized form of a short phrase (a skill keyword or action
    verb). Falls back to a plain lowercase pass-through if spaCy isn't available,
    which reproduces the app's original exact-match behaviour."""
    if nlp is None:
        return phrase.lower().strip()
    key = phrase.lower().strip()
    if key in _phrase_lemma_cache:
        return _phrase_lemma_cache[key]
    lemma = " ".join(tok.lemma_.lower() for tok in nlp(key) if not tok.is_space)
    _phrase_lemma_cache[key] = lemma
    return lemma

def analyze_document_with_nlp(raw_text):
    """Runs spaCy once per resume and returns (lemmatized_text, verb_lemmas):
    - lemmatized_text: the whole resume, lemmatized and lowercased, used for
      skill/keyword matching against lemmatized skill phrases.
    - verb_lemmas: the set of base-form verb lemmas spaCy found in the resume,
      used for tense/inflection-independent action-verb detection.
    Falls back to (plain lowercase text, empty set) if spaCy isn't available —
    callers already handle that combination as the original plain-text path."""
    if nlp is None:
        return raw_text.lower(), set()
    doc = nlp(raw_text)
    lemmatized_text = " ".join(tok.lemma_.lower() for tok in doc if not tok.is_space)
    verb_lemmas = {tok.lemma_.lower() for tok in doc if tok.pos_ == "VERB"}
    return lemmatized_text, verb_lemmas

# --- DATABASE SETUP (SQLite) ---
DB_FILE = 'roles.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_name TEXT UNIQUE NOT NULL,
            skills TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            selected_role TEXT,
            ats_score INTEGER,
            quality_score INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_all_roles_dict():
    conn = get_db_connection()
    roles_rows = conn.execute("SELECT role_name, skills FROM roles").fetchall()
    conn.close()
    
    roles_dict = {}
    for row in roles_rows:
        skills_list = [s.strip().lower() for s in row['skills'].split(',') if s.strip()]
        roles_dict[row['role_name']] = skills_list
    return roles_dict

# --- HELPER ANALYSIS FUNCTIONS ---
# Base/lemma forms, used when spaCy is available (matches "develop", "developed",
# "developing", "develops" alike via POS-tagged lemmatization).
ACTION_VERB_LEMMAS = ["develop", "engineer", "design", "implement", "manage",
                      "lead", "build", "create", "architect", "optimize", "increase", "reduce"]
# Original inflected forms, used only as a fallback when spaCy/model isn't
# available — preserves the app's exact original behaviour in that case.
ACTION_VERBS_FALLBACK = ["developed", "engineered", "designed", "implemented", "managed",
                         "led", "built", "created", "architected", "optimized", "increased", "reduced"]

def analyze_resume_text(raw_text, target_role):
    roles = get_all_roles_dict()
    text_lower = raw_text.lower()
    lemmatized_text, verb_lemmas_found = analyze_document_with_nlp(raw_text)

    target_keywords = roles.get(target_role, [])
    found_skills = [kw for kw in target_keywords
                     if re.search(r'\b' + re.escape(lemmatize_phrase(kw)) + r'\b', lemmatized_text)]
    missing_skills = [kw for kw in target_keywords if kw not in found_skills]
    
    ats_score = int((len(found_skills) / len(target_keywords) * 100)) if target_keywords else 0

    headers = ["EXPERIENCE", "WORK EXPERIENCE", "EDUCATION", "SKILLS", "SUMMARY", "PROJECTS"]
    detected_headers = [h for h in headers if h in raw_text.upper()]

    if nlp is not None:
        found_verbs = [v for v in ACTION_VERB_LEMMAS if v in verb_lemmas_found]
    else:
        found_verbs = [v for v in ACTION_VERBS_FALLBACK if re.search(r'\b' + re.escape(v) + r'\b', text_lower)]

    has_email = bool(re.search(r'[\w\.-]+@[\w\.-]+\.\w+', raw_text))
    has_phone = bool(re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', raw_text))

    skills_points = int((ats_score / 100) * 50)
    verbs_points = min(len(found_verbs) * 3, 20)
    structure_points = min(len(detected_headers) * 4, 20)
    contact_points = (5 if has_email else 0) + (5 if has_phone else 0)

    quality_score = skills_points + verbs_points + structure_points + contact_points

    score_breakdown = [
        {
            "category": "Target Skills Match",
            "score": f"{skills_points} / 50",
            "criteria": f"Matched {len(found_skills)} of {len(target_keywords)} target skills for '{target_role}'."
        },
        {
            "category": "Action & Impact Verbs",
            "score": f"{verbs_points} / 20",
            "criteria": f"Identified {len(found_verbs)} strong action verbs ({', '.join(found_verbs[:4]) if found_verbs else 'None found'})."
        },
        {
            "category": "Section Structure & Layout",
            "score": f"{structure_points} / 20",
            "criteria": f"Found {len(detected_headers)} standard sections ({', '.join(detected_headers[:3]) if detected_headers else 'None'})."
        },
        {
            "category": "Contact Information Audit",
            "score": f"{contact_points} / 10",
            "criteria": f"Email: {'Found' if has_email else 'Missing'} | Phone: {'Found' if has_phone else 'Missing'}."
        }
    ]

    role_matches = {}
    best_matching_role = target_role
    best_matching_score = ats_score

    for r_name, r_skills in roles.items():
        matched = [sk for sk in r_skills
                   if re.search(r'\b' + re.escape(lemmatize_phrase(sk)) + r'\b', lemmatized_text)]
        match_pct = int((len(matched) / len(r_skills) * 100)) if r_skills else 0
        role_matches[r_name] = {"ats_percentage": match_pct, "matched_skills": matched}
        
        if match_pct > best_matching_score:
            best_matching_score = match_pct
            best_matching_role = r_name

    feedback = []
    if missing_skills:
        feedback.append(f"Consider adding missing core skills: {', '.join(missing_skills[:5])}.")
    if len(found_verbs) < 3:
        feedback.append("Use more strong action verbs (e.g., engineered, optimized, spearheaded).")
    if not has_email or not has_phone:
        feedback.append("Ensure clear email address and phone number are visible at the top.")

    return {
        "active_role_label": target_role,
        "nlp_enabled": NLP_ENABLED,
        "ats_score": ats_score,
        "quality_score": quality_score,
        "score_breakdown": score_breakdown,
        "best_matching_role": best_matching_role,
        "best_matching_score": best_matching_score,
        "role_matches": role_matches,
        "target_keywords": target_keywords,
        "selected_found_skills": found_skills,
        "selected_missing_skills": missing_skills,
        "action_verb_count": len(found_verbs),
        "feedback": feedback,
        "raw_text": raw_text
    }

# --- ROUTES ---

@app.route('/', methods=['GET', 'POST'])
def index():
    roles = get_all_roles_dict()
    available_roles = list(roles.keys())
    selected_role = available_roles[0] if available_roles else ""

    if request.method == 'POST':
        selected_role = request.form.get('role', selected_role)
        file = request.files.get('resume')
        
        raw_text = ""
        filename = "uploaded_resume.txt"
        
        if file and file.filename:
            filename = file.filename
            file_bytes = file.read()
            if filename.lower().endswith('.pdf'):
                try:
                    import pypdf
                    import io
                    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                    for page in reader.pages:
                        extracted = page.extract_text()
                        if extracted:
                            raw_text += extracted + "\n"
                except Exception as e:
                    raw_text = f"Error reading PDF file: {str(e)}"
            elif filename.lower().endswith('.docx'):
                try:
                    import docx
                    import io
                    doc = docx.Document(io.BytesIO(file_bytes))
                    for para in doc.paragraphs:
                        raw_text += para.text + "\n"
                except Exception as e:
                    raw_text = f"Error reading DOCX file: {str(e)}"
            else:
                try:
                    raw_text = file_bytes.decode('utf-8', errors='ignore')
                except Exception:
                    raw_text = "Could not decode uploaded file."
        
        if not raw_text.strip():
            raw_text = "No extractable text found in the uploaded document."

        results = analyze_resume_text(raw_text, selected_role)
        session['results'] = results
        
        conn = get_db_connection()
        conn.execute("INSERT INTO history (filename, selected_role, ats_score, quality_score) VALUES (?, ?, ?, ?)",
                     (filename, selected_role, results['ats_score'], results['quality_score']))
        conn.commit()
        conn.close()

    results = session.get('results', None)
    return render_template('index.html', available_roles=available_roles, role=selected_role, results=results)

@app.route('/clear-analysis', methods=['POST'])
def clear_analysis():
    session.pop('results', None)
    return redirect(url_for('index'))

@app.route('/manage-roles', methods=['GET', 'POST'])
def manage_roles():
    conn = get_db_connection()
    if request.method == 'POST':
        role_name = request.form.get('role_name', '').strip()
        skills = request.form.get('skills', '').strip()
        
        if role_name and skills:
            try:
                conn.execute("INSERT INTO roles (role_name, skills) VALUES (?, ?)", (role_name, skills))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
        return redirect(url_for('manage_roles'))

    roles_list = conn.execute("SELECT * FROM roles ORDER BY role_name ASC").fetchall()
    conn.close()
    return render_template('manage_roles.html', roles=roles_list)

@app.route('/delete-role/<int:role_id>', methods=['POST'])
def delete_role(role_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('manage_roles'))

@app.route('/history')
def history():
    conn = get_db_connection()
    logs = conn.execute("SELECT * FROM history ORDER BY timestamp DESC").fetchall()
    conn.close()
    return render_template('history.html', logs=logs)

@app.route('/delete-history/<int:log_id>', methods=['POST'])
def delete_history(log_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM history WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('history'))

@app.route('/clear-history', methods=['POST'])
def clear_history():
    conn = get_db_connection()
    conn.execute("DELETE FROM history")
    conn.commit()
    conn.close()
    return redirect(url_for('history'))

if __name__ == '__main__':
    app.run(debug=True)