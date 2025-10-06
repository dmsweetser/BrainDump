from html import unescape
import os
import hashlib
import json
from datetime import datetime, timedelta
import re
import threading
import queue
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

import sqlite3
import webbrowser
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import html2text

from lib.config import Config
from lib.revisor import Revisor

load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['DEBUG'] = Config.DEBUG

# Initialize directories
for directory in [Config.HTML_OUTPUT]:
    Path(directory).mkdir(exist_ok=True)

# Initialize database
def init_db():
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hash TEXT UNIQUE NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_number INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            html_content TEXT NOT NULL,
            diff_with_previous TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Generate note hash
def generate_note_hash(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

# Save note (no title)
def save_note(content):
    if not content.strip():
        return None
    note_hash = generate_note_hash(content)
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO notes (content, hash)
            VALUES (?, ?)
        ''', (content, note_hash))
        note_id = cursor.lastrowid
        conn.commit()
        # Queue document regeneration
        revision_queue.put(note_id)
        return note_id
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    finally:
        conn.close()

# Get all notes
def get_all_notes():
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, content, created_at FROM notes ORDER BY created_at DESC')
    notes = cursor.fetchall()
    conn.close()
    return [
        {'id': note[0], 'content': note[1], 'created_at': note[2]}
        for note in notes
    ]

# Get latest revision timestamp
def get_latest_revision_timestamp():
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(timestamp) FROM document_history')
    result = cursor.fetchone()
    conn.close()
    return result[0] if result[0] else None

# Get only notes newer than last revision
def get_new_notes_since_revision():
    latest_timestamp = get_latest_revision_timestamp()
    if not latest_timestamp:
        return get_all_notes()
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, content, created_at 
        FROM notes 
        WHERE created_at > ? 
        ORDER BY created_at ASC
    ''', (latest_timestamp,))
    new_notes = cursor.fetchall()
    conn.close()
    return [
        {'id': note[0], 'content': note[1], 'created_at': note[2]}
        for note in new_notes
    ]

def sanitize_diff_content(html_content):
    """
    Convert HTML content to plain text while preserving structure
    """
    if not html_content or not isinstance(html_content, str):
        return ""
    
    # First, handle any HTML entities
    html_content = unescape(html_content)
    
    # Create html2text converter
    h = html2text.HTML2Text()
    
    # Configure the converter
    h.body_width = 0  # Don't wrap lines
    h.ignore_links = False  # Keep links as text
    h.ignore_images = True  # Don't include image alt text
    h.ignore_emphasis = False  # Preserve bold/italic
    h.ignore_tables = False  # Keep table structure
    h.single_line_break = True  # Use single line breaks
    h.body_width = 1000  # Prevent line wrapping
    h.escape_snob = True  # Escape special characters
    
    # Convert HTML to plain text
    plain_text = h.handle(html_content)
    
    # Clean up extra whitespace
    plain_text = re.sub(r'\n\s*\n', '\n\n', plain_text)  # Remove extra blank lines
    plain_text = re.sub(r'\n{3,}', '\n\n', plain_text)  # Limit consecutive blank lines
    plain_text = plain_text.strip()
    
    return plain_text

# Get document history
def get_document_history():
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, version_number, timestamp, html_content, diff_with_previous FROM document_history ORDER BY timestamp DESC')
    history = cursor.fetchall()
    conn.close()
    return [
        {
            'id': item[0],
            'version_number': item[1],
            'timestamp': item[2],
            'html_content': item[3],
            'diff_with_previous': item[4]
        }
        for item in history
    ]

# Generate diff between two versions
def generate_diff(old_content: str, new_content: str) -> str:
    from difflib import SequenceMatcher
    s = SequenceMatcher(None, old_content, new_content)
    diff_lines = []
    for tag, i1, i2, j1, j2 in s.get_opcodes():
        if tag == 'equal':
            continue
        elif tag == 'replace':
            diff_lines.append(f"Changed: {new_content[j1:j2]}")
        elif tag == 'delete':
            diff_lines.append(f"Removed: {old_content[i1:i2]}")
        elif tag == 'insert':
            diff_lines.append(f"Added: {new_content[j1:j2]}")
    return "\n".join(diff_lines[:10])

# Regenerate document (run in thread)
def regenerate_document_worker():
    while True:
        try:
            note_id = revision_queue.get(timeout=1)
            if note_id is None:
                break

            # Get only **new** notes since last revision
            new_notes = get_new_notes_since_revision()
            if not new_notes:
                revision_queue.task_done()
                continue

            # Get latest document HTML
            history = get_document_history()
            latest_html = history[0]['html_content'] if history else ""

            # Prepare input for AI: just the raw content
            new_notes_text = "\n".join([
                f"New content block:\n{note['content']}"
                for note in new_notes
            ])

            # Initialize AI Builder
            revisor = Revisor()

            # Run AI to get `replace_section` actions
            html_content = revisor.run(current_document=latest_html, instructions=new_notes_text)

            conn = sqlite3.connect(Config.DATABASE)
            cursor = conn.cursor()
            cursor.execute('SELECT MAX(version_number) FROM document_history')
            result = cursor.fetchone()
            conn.close()
            version_number = (result[0] or 0) + 1

            timestamp = datetime.now()
            file_timestamp = timestamp.strftime("%Y%m%d_%H%M%S")
            html_filename = f"brain_dump_v{version_number}_{file_timestamp}.html"
            html_path = os.path.join(Config.HTML_OUTPUT, html_filename)

            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # Calculate diff with previous version
            diff_with_previous = ""
            if history:
                previous_html = history[0]['html_content']
                diff_with_previous = generate_diff(previous_html, html_content)

            # Save the new version to document_history table
            conn = sqlite3.connect(Config.DATABASE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO document_history (version_number, timestamp, html_content, diff_with_previous)
                VALUES (?, ?, ?, ?)
            ''', (version_number, timestamp, html_content, diff_with_previous))
            conn.commit()
            conn.close()

            # Email new version
            if Config.SMTP_ENABLED and Config.EMAIL_SENDER and Config.EMAIL_RECIPIENTS:
                send_email_notification(version_number, html_path)

            revision_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"Error in regeneration worker: {e}")

# Send email notification
def send_email_notification(version: int, html_path: str):
    try:
        msg = MIMEMultipart()
        msg['From'] = Config.EMAIL_SENDER
        msg['To'] = ', '.join(Config.EMAIL_RECIPIENTS)
        msg['Subject'] = f"Brain Dump - New Document Version {version}"

        body = f"New document version {version} has been generated."
        msg.attach(MIMEText(body, 'plain'))

        # Attach HTML
        with open(html_path, "r", encoding="utf-8") as f:
            html_body = f.read()
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)

        server = smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT)
        server.starttls()
        server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
        server.sendmail(Config.EMAIL_SENDER, Config.EMAIL_RECIPIENTS, msg.as_string())
        server.quit()
        print(f"Email sent for version {version}")
    except Exception as e:
        print(f"Email failed: {e}")

# Start revision worker thread
revision_queue = queue.Queue()
threading.Thread(target=regenerate_document_worker, daemon=True).start()

# Routes

@app.route('/')
def index():
    notes = get_all_notes()
    history = get_document_history()
    latest_version = history[0] if history else None
    return render_template('index.html', notes=notes, history=history, latest_version=latest_version)

@app.route('/add_note', methods=['POST'])
def add_note():
    content = request.form.get('content', '').strip()
    if not content:
        return jsonify({'error': 'Content is required'}), 400
    note_id = save_note(content)
    if note_id is None:
        return jsonify({'error': 'Duplicate content detected'}), 400
    return jsonify({'success': True, 'message': 'Note added successfully', 'note_id': note_id})

@app.route('/delete_note/<int:note_id>', methods=['POST'])
def delete_note(note_id):
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT content FROM notes WHERE id = ?', (note_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Note not found'}), 404
        cursor.execute('DELETE FROM notes WHERE id = ?', (note_id,))
        if cursor.rowcount > 0:
            revision_queue.put(note_id)
            conn.commit()
            return jsonify({'success': True, 'message': 'Note deleted successfully'})
        return jsonify({'error': 'Note not found'}), 404
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/edit_note/<int:note_id>', methods=['POST'])
def edit_note(note_id):
    content = request.form.get('content', '').strip()
    if not content:
        return jsonify({'error': 'Content is required'}), 400
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id FROM notes WHERE id = ?', (note_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Note not found'}), 404
        cursor.execute('UPDATE notes SET content = ? WHERE id = ?', (content, note_id))
        revision_queue.put(note_id)
        conn.commit()
        return jsonify({'success': True, 'message': 'Note updated successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/export_html/<int:version_id>')
def export_html(version_id):
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT html_content, timestamp FROM document_history WHERE id = ?', (version_id,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return jsonify({'error': 'Version not found'}), 404
    html_content, timestamp = result
    filename = f"brain_dump_v{version_id}_{timestamp}.html"
    return jsonify({'success': True, 'filename': filename, 'content': html_content})

@app.route('/export_all_notes')
def export_all_notes():
    notes = get_all_notes()
    content = ""
    for note in notes:
        content += f"=== Added: {note['created_at']} ===\n"
        content += f"{note['content']}\n\n"
    filename = f"all_notes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return jsonify({'success': True, 'filename': filename, 'content': content})

@app.route('/api/notes')
def api_notes():
    return jsonify(get_all_notes())

@app.route('/api/history')
def api_history():
    return jsonify(get_document_history())

def open_browser():
    webbrowser.open_new("http://127.0.0.1:5983")

if __name__ == '__main__':
    init_db()
    threading.Timer(5, open_browser).start()
    app.run(host="0.0.0.0", port="5983", debug=Config.DEBUG)