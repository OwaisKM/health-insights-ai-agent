"""
app.py — Main Flask Application for Health Insights AI Agent (HIA)
Handles all routes: auth, health form, AI analysis, chat, PDF download.
"""

# Fix Windows console encoding for emoji/unicode in AI responses
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import os
import time
import uuid
from datetime import datetime, timezone
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_file
)
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from bson import ObjectId

# Load environment variables from .env
load_dotenv()

# Import our utility modules
from utils.db import get_users, get_records
from utils.ai_helper import analyze_health_data, chat_with_ai
from utils.pdf_generator import generate_pdf_report

# =====================
# App Configuration
# =====================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "hia-secret-key-change-this")

bcrypt = Bcrypt(app)

# Directory to temporarily store generated PDFs
PDF_FOLDER = os.path.join(os.path.dirname(__file__), "static", "reports")
os.makedirs(PDF_FOLDER, exist_ok=True)

# Max age (seconds) before a generated PDF is considered stale and deleted
PDF_MAX_AGE_SECONDS = 60 * 60  # 1 hour


def cleanup_old_pdfs():
    """
    Delete PDF files in PDF_FOLDER that are older than PDF_MAX_AGE_SECONDS.
    Called automatically after every successful PDF download so the folder
    never accumulates stale reports.
    """
    now = time.time()
    try:
        for fname in os.listdir(PDF_FOLDER):
            if not fname.lower().endswith(".pdf"):
                continue
            fpath = os.path.join(PDF_FOLDER, fname)
            try:
                age = now - os.path.getmtime(fpath)
                if age > PDF_MAX_AGE_SECONDS:
                    os.remove(fpath)
                    app.logger.info("Deleted stale PDF: %s (age %.0fs)", fname, age)
            except OSError:
                pass  # File already gone or locked — skip silently
    except OSError:
        pass  # Folder issue — non-fatal


# =====================
# Helper Functions
# =====================

def is_logged_in():
    """Check if a user is currently in the session."""
    return "user_id" in session


def login_required(f):
    """Decorator to protect routes that need login."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_logged_in():
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# =====================
# Routes
# =====================

@app.route("/")
def index():
    """Landing page — shows the main HIA home page."""
    return render_template("index.html", logged_in=is_logged_in(),
                           username=session.get("username", ""))


# ------- AUTH ROUTES -------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    """User registration page."""
    if is_logged_in():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")

        # Basic validation
        if not all([name, email, password, confirm]):
            flash("All fields are required.", "danger")
            return render_template("signup.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("signup.html")

        try:
            users = get_users()
        except RuntimeError as exc:
            flash(str(exc), "danger")
            return render_template("signup.html")

        # Check if email already registered
        if users.find_one({"email": email}):
            flash("An account with this email already exists.", "danger")
            return render_template("signup.html")

        # Hash password and store user
        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
        user_doc = {
            "name": name,
            "email": email,
            "password": hashed_pw,
            "created_at": datetime.now(timezone.utc),
        }
        result = users.insert_one(user_doc)

        # Auto-login after signup
        session["user_id"] = str(result.inserted_id)
        session["username"] = name
        session["email"] = email

        flash(f"Welcome to HIA, {name}! 🎉 Your account is ready.", "success")
        return redirect(url_for("dashboard"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """User login page."""
    if is_logged_in():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter your email and password.", "danger")
            return render_template("login.html")

        try:
            users = get_users()
        except RuntimeError as exc:
            flash(str(exc), "danger")
            return render_template("login.html")

        user = users.find_one({"email": email})

        if user and bcrypt.check_password_hash(user["password"], password):
            session["user_id"] = str(user["_id"])
            session["username"] = user["name"]
            session["email"] = user["email"]
            flash(f"Welcome back, {user['name']}! 👋", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password. Please try again.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Clear the session and log the user out."""
    session.clear()
    flash("You've been logged out. See you soon! 👋", "info")
    return redirect(url_for("index"))


# ------- DASHBOARD -------

@app.route("/dashboard")
@login_required
def dashboard():
    """User dashboard — shows their past health records."""
    records = get_records()
    # Fetch all records for this user, newest first
    user_records = list(
        records.find({"user_id": session["user_id"]}).sort("created_at", -1)
    )
    return render_template(
        "dashboard.html",
        username=session.get("username"),
        records=user_records
    )


# ------- HEALTH FORM -------

@app.route("/form")
@login_required
def form():
    """Health data input form."""
    return render_template("form.html", username=session.get("username"))


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    """
    Receive health form data, call the AI for analysis,
    save the record to MongoDB, and show results.
    """
    # Collect all form fields
    health_data = {
        "name"               : request.form.get("name", session.get("username")),
        "age"                : request.form.get("age", ""),
        "gender"             : request.form.get("gender", ""),
        "height"             : request.form.get("height", ""),
        "weight"             : request.form.get("weight", ""),
        "blood_group"        : request.form.get("blood_group", ""),
        "symptoms"           : request.form.get("symptoms", ""),
        "blood_pressure"     : request.form.get("blood_pressure", ""),
        "blood_sugar"        : request.form.get("blood_sugar", ""),
        "heart_rate"         : request.form.get("heart_rate", ""),
        "sleep_hours"        : request.form.get("sleep_hours", ""),
        "exercise"           : request.form.get("exercise", ""),
        "diet_type"          : request.form.get("diet_type", ""),
        "smoking"            : request.form.get("smoking", "No"),
        "alcohol"            : request.form.get("alcohol", "No"),
        "stress_level"       : request.form.get("stress_level", ""),
        "health_goals"       : request.form.get("health_goals", ""),
        "existing_conditions": request.form.get("existing_conditions", ""),
    }

    try:
        # Call AI for analysis
        analysis = analyze_health_data(health_data)

        # Save record to MongoDB
        record_doc = {
            "user_id"    : session["user_id"],
            "health_data": health_data,
            "analysis"   : analysis,
            "created_at" : datetime.now(timezone.utc),
        }
        records = get_records()
        result = records.insert_one(record_doc)
        record_id = str(result.inserted_id)

        # Store in session for PDF generation
        session["last_record_id"] = record_id

        return render_template(
            "result.html",
            health_data=health_data,
            analysis=analysis,
            record_id=record_id,
            username=session.get("username")
        )

    except Exception as e:
        flash(f"AI analysis failed: {str(e)}", "danger")
        return redirect(url_for("form"))


# ------- RESULT (View Saved Record) -------

@app.route("/result/<record_id>")
@login_required
def view_result(record_id):
    """View a previously saved health analysis."""
    records = get_records()
    try:
        record = records.find_one({"_id": ObjectId(record_id), "user_id": session["user_id"]})
    except Exception:
        flash("Record not found.", "danger")
        return redirect(url_for("dashboard"))

    if not record:
        flash("Record not found or access denied.", "danger")
        return redirect(url_for("dashboard"))

    return render_template(
        "result.html",
        health_data=record["health_data"],
        analysis=record["analysis"],
        record_id=record_id,
        username=session.get("username")
    )


# ------- PDF DOWNLOAD -------

@app.route("/download-pdf/<record_id>")
@login_required
def download_pdf(record_id):
    """Generate and download a PDF report for a health record."""
    records = get_records()
    try:
        record = records.find_one({"_id": ObjectId(record_id), "user_id": session["user_id"]})
    except Exception:
        flash("Invalid record ID.", "danger")
        return redirect(url_for("dashboard"))

    if not record:
        flash("Record not found.", "danger")
        return redirect(url_for("dashboard"))

    # Generate PDF
    filename = f"HIA_Report_{record_id[:8]}_{datetime.now().strftime('%Y%m%d')}.pdf"
    output_path = os.path.join(PDF_FOLDER, filename)

    try:
        generate_pdf_report(record["health_data"], record["analysis"], output_path)
        response = send_file(output_path, as_attachment=True, download_name=filename)
        # Clean up PDFs older than 1 hour after serving this one
        cleanup_old_pdfs()
        return response
    except Exception as e:
        flash(f"Failed to generate PDF: {str(e)}", "danger")
        return redirect(url_for("view_result", record_id=record_id))


# ------- AI CHAT (AJAX) -------

@app.route("/chat", methods=["POST"])
@login_required
def chat():
    """
    Handle live chat messages via AJAX.
    Expects JSON: { "message": "...", "history": [...] }
    Returns JSON: { "reply": "..." }
    """
    data = request.get_json()
    user_message = data.get("message", "").strip()
    history = data.get("history", [])

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    try:
        reply = chat_with_ai(user_message, history)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------- DELETE RECORD -------

@app.route("/delete-record/<record_id>", methods=["POST"])
@login_required
def delete_record(record_id):
    """Delete a health record belonging to the current user."""
    records = get_records()
    try:
        records.delete_one({"_id": ObjectId(record_id), "user_id": session["user_id"]})
        flash("Record deleted successfully.", "success")
    except Exception:
        flash("Failed to delete record.", "danger")
    return redirect(url_for("dashboard"))


# =====================
# Run the App
# =====================
if __name__ == "__main__":
    import platform

    if platform.system() == "Windows":
        # -----------------------------------------------------------
        # Windows: use waitress (a stable, threading-safe WSGI server)
        # Werkzeug's built-in dev server on Windows + Python 3.10
        # triggers WinError 10038 in its reloader background thread.
        # waitress has none of these issues.
        # Install: pip install waitress
        # -----------------------------------------------------------
        try:
            from waitress import serve
            print(" * Running on http://127.0.0.1:5000")
            print(" * Debug mode: on  |  Press CTRL+C to quit")
            serve(app, host="0.0.0.0", port=5000, threads=4)
        except ImportError:
            # waitress not installed — fall back to Werkzeug without reloader
            print(" * waitress not found. Falling back to Werkzeug (no auto-reload).")
            print(" * Install waitress for a better Windows experience: pip install waitress")
            app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
    else:
        # Linux / macOS — standard Flask dev server works perfectly
        app.run(debug=True, host="0.0.0.0", port=5000)
