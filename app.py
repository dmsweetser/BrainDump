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
import logging
import traceback

import sqlite3
import webbrowser
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import html2text

from lib.config import Config
from lib.revisor import Revisor

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)

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
    try:
        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_deleted INTEGER DEFAULT 0,
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
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        conn.close()

# Generate note hash
def generate_note_hash(content):
    try:
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    except Exception as e:
        logger.error(f"Error generating note hash: {e}")
        raise

def save_note(content):
    if not content.strip():
        logger.warning("Attempted to save empty note content")
        return None
    try:
        note_hash = generate_note_hash(content)
        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO notes (content, created_at, modified_at, is_deleted, hash)
                VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, ?)
            ''', (content, note_hash))
            note_id = cursor.lastrowid
            conn.commit()
            revision_queue.put(note_id)
            logger.info(f"Note saved successfully with ID: {note_id}")
            return note_id
        except sqlite3.IntegrityError:
            conn.rollback()
            logger.warning(f"Duplicate content detected for note with hash: {note_hash}")
            return None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving note: {e}")
            raise
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Error in save_note: {e}")
        raise

# Get all notes
def get_all_notes():
    try:
        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        cursor.execute('SELECT id, content, created_at, modified_at, is_deleted FROM notes ORDER BY created_at DESC')
        notes = cursor.fetchall()
        conn.close()
        logger.info(f"Retrieved {len(notes)} notes from database")
        return [
            {'id': note[0], 'content': note[1], 'created_at': note[2], 'modified_at': note[3], 'is_deleted': note[4]}
            for note in notes
        ]
    except Exception as e:
        logger.error(f"Error retrieving all notes: {e}")
        raise

# Get latest revision timestamp
def get_latest_revision_timestamp():
    try:
        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(timestamp) FROM document_history')
        result = cursor.fetchone()
        conn.close()
        timestamp = result[0] if result[0] else None
        logger.info(f"Latest revision timestamp: {timestamp}")
        return timestamp
    except Exception as e:
        logger.error(f"Error getting latest revision timestamp: {e}")
        raise

# Get only notes newer than last revision
def get_new_notes_since_revision():
    try:
        latest_timestamp = get_latest_revision_timestamp()
        if not latest_timestamp:
            logger.info("No previous revisions found, retrieving all notes")
            return get_all_notes()

        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, content, created_at, modified_at, is_deleted
            FROM notes
            WHERE created_at > ? OR modified_at > ?
            ORDER BY modified_at ASC
        ''', (latest_timestamp, latest_timestamp))
        new_notes = cursor.fetchall()
        conn.close()
        logger.info(f"Retrieved {len(new_notes)} new notes since last revision")
        return [
            {
                'id': note[0],
                'content': note[1],
                'created_at': note[2],
                'modified_at': note[3],
                'is_deleted': note[4]
            }
            for note in new_notes
        ]
    except Exception as e:
        logger.error(f"Error getting new notes since revision: {e}")
        raise

def sanitize_diff_content(html_content):
    """
    Convert HTML content to plain text while preserving structure
    """
    try:
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
        
        logger.debug("Successfully sanitized diff content")
        return plain_text
    except Exception as e:
        logger.error(f"Error sanitizing diff content: {e}")
        return ""

# Get document history
def get_document_history():
    try:
        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        cursor.execute('SELECT id, version_number, timestamp, html_content, diff_with_previous FROM document_history ORDER BY timestamp DESC')
        history = cursor.fetchall()
        conn.close()
        logger.info(f"Retrieved {len(history)} document history entries")
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
    except Exception as e:
        logger.error(f"Error retrieving document history: {e}")
        raise

# Generate diff between two versions
def generate_diff(old_content: str, new_content: str) -> str:
    try:
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
        diff_result = "\n".join(diff_lines[:10])
        logger.debug(f"Generated diff with {len(diff_lines)} changes")
        return diff_result
    except Exception as e:
        logger.error(f"Error generating diff: {e}")
        return ""

# Regenerate document (run in thread)
def regenerate_document_worker():
    while True:
        try:
            note_id = revision_queue.get(timeout=1)
            if note_id is None:
                break

            logger.info(f"Processing revision for note ID: {note_id}")

            # Get all changes since last revision
            new_notes = get_new_notes_since_revision()
            if not new_notes:
                logger.info("No new notes to process, marking task as done")
                revision_queue.task_done()
                continue

            # Fetch current document
            history = get_document_history()
            latest_html = history[0]['html_content'] if history else ""

            # Build instructions with change context
            instructions = []
            for note in new_notes:
                if note['created_at'] == note['modified_at']:
                    instructions.append(f"ADDED: New content block:\n{note['content']}")
                elif int(note['is_deleted']) == 1:
                    instructions.append(f"DELETED: Existing content block:\n{note['content']}")
                else:
                    # Fetch original content for edit
                    conn = sqlite3.connect(Config.DATABASE)
                    cursor = conn.cursor()
                    cursor.execute('SELECT content FROM notes WHERE id = ?', (note['id'],))
                    original = cursor.fetchone()
                    conn.close()
                    if original:
                        instructions.append(
                            f"CHANGED: Note ID {note['id']} modified from:\n{original[0]}\n\nTO:\n{note['content']}"
                        )
                    else:
                        instructions.append(f"CHANGED: Note ID {note['id']} modified to:\n{note['content']}")

            # Join instructions
            instructions_text = "\n\n".join(instructions)
            logger.info(f"Generated instructions with {len(instructions)} change items")

            # Run Revisor
            revisor = Revisor()
            logger.info("Starting document regeneration with Revisor")
            html_content = revisor.run(current_document=latest_html, instructions=instructions_text)

            # Save version
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

            try:
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                logger.info(f"Saved new document version {version_number} to {html_path}")
            except Exception as e:
                logger.error(f"Failed to save document to {html_path}: {e}")
                raise

            # Generate diff
            diff_with_previous = ""
            if history:
                previous_html = history[0]['html_content']
                diff_with_previous = generate_diff(previous_html, html_content)
                logger.info(f"Generated diff for version {version_number}")

            # Save to history
            conn = sqlite3.connect(Config.DATABASE)
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO document_history (version_number, timestamp, html_content, diff_with_previous)
                    VALUES (?, ?, ?, ?)
                ''', (version_number, timestamp, html_content, diff_with_previous))
                conn.commit()
                logger.info(f"Saved document history entry for version {version_number}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to save document history: {e}")
                raise
            finally:
                conn.close()

            # Send email
            if Config.SMTP_ENABLED and Config.EMAIL_SENDER and Config.EMAIL_RECIPIENTS:
                try:
                    send_email_notification(version_number, html_path)
                except Exception as e:
                    logger.error(f"Failed to send email notification: {e}")

            revision_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Error in regeneration worker: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Don't break the loop - continue processing

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
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_body = f.read()
            html_part = MIMEText(html_body, 'html')
            msg.attach(html_part)
            logger.info(f"Successfully attached HTML file: {html_path}")
        except Exception as e:
            logger.error(f"Failed to read HTML file {html_path}: {e}")
            raise

        server = smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT)
        try:
            server.starttls()
            server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
            server.sendmail(Config.EMAIL_SENDER, Config.EMAIL_RECIPIENTS, msg.as_string())
            server.quit()
            logger.info(f"Email sent successfully for version {version}")
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            raise
    except Exception as e:
        logger.error(f"Email failed: {e}")
        raise

# Start revision worker thread
revision_queue = queue.Queue()
threading.Thread(target=regenerate_document_worker, daemon=True).start()

# Routes

@app.route('/')
def index():
    try:
        notes = get_all_notes()
        history = get_document_history()
        latest_version = history[0] if history else None
        logger.info("Served index page")
        return render_template('index.html', notes=notes, history=history, latest_version=latest_version)
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return f"Error: {e}", 500

@app.route('/add_note', methods=['POST'])
def add_note():
    try:
        content = request.form.get('content', '').strip()
        if not content:
            logger.warning("Attempted to add note with empty content")
            return jsonify({'error': 'Content is required'}), 400
        note_id = save_note(content)
        if note_id is None:
            logger.warning("Attempted to add duplicate note content")
            return jsonify({'error': 'Duplicate content detected'}), 400
        logger.info(f"Successfully added note with ID: {note_id}")
        return jsonify({'success': True, 'message': 'Note added successfully', 'note_id': note_id})
    except Exception as e:
        logger.error(f"Error adding note: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/delete_note/<int:note_id>', methods=['POST'])
def delete_note(note_id):
    try:
        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        try:
            # Update the note
            cursor.execute('''
                UPDATE notes 
                SET is_deleted = 1, modified_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (note_id,))
            if cursor.rowcount == 0:
                logger.warning(f"Attempted to delete non-existent note with ID: {note_id}")
                return jsonify({'error': 'Note not found'}), 404

            # Send revision with context
            revision_queue.put(note_id)
            logger.info(f"Note {note_id} marked for deletion and queued for revision")

            conn.commit()
            return jsonify({'success': True, 'message': 'Note deleted successfully'})

        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting note {note_id}: {e}")
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Error in delete_note route: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/edit_note/<int:note_id>', methods=['POST'])
def edit_note(note_id):
    try:
        content = request.form.get('content', '').strip()
        if not content:
            logger.warning(f"Attempted to edit note {note_id} with empty content")
            return jsonify({'error': 'Content is required'}), 400

        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        try:
            # Fetch original content
            cursor.execute('SELECT content FROM notes WHERE id = ?', (note_id,))
            original_result = cursor.fetchone()
            if not original_result:
                logger.warning(f"Attempted to edit non-existent note with ID: {note_id}")
                return jsonify({'error': 'Note not found'}), 404
            original_content = original_result[0]

            # Update the note
            cursor.execute('''
                UPDATE notes 
                SET content = ?, modified_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (content, note_id))
            if cursor.rowcount == 0:
                logger.warning(f"Attempted to edit non-existent note with ID: {note_id}")
                return jsonify({'error': 'Note not found'}), 404

            # Send revision with context
            revision_queue.put(note_id)
            logger.info(f"Note {note_id} updated and queued for revision")

            conn.commit()
            return jsonify({'success': True, 'message': 'Note updated successfully'})

        except Exception as e:
            conn.rollback()
            logger.error(f"Error editing note {note_id}: {e}")
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Error in edit_note route: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/export_html/<int:version_id>')
def export_html(version_id):
    try:
        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        cursor.execute('SELECT html_content, timestamp FROM document_history WHERE id = ?', (version_id,))
        result = cursor.fetchone()
        conn.close()
        if not result:
            logger.warning(f"Attempted to export non-existent version {version_id}")
            return jsonify({'error': 'Version not found'}), 404
        html_content, timestamp = result
        filename = f"brain_dump_v{version_id}_{timestamp}.html"
        logger.info(f"Exported version {version_id} as {filename}")
        return jsonify({'success': True, 'filename': filename, 'content': html_content})
    except Exception as e:
        logger.error(f"Error exporting HTML version {version_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/export_all_notes')
def export_all_notes():
    try:
        notes = get_all_notes()
        content = ""
        for note in notes:
            content += f"=== Added: {note['created_at']} ===\n"
            content += f"{note['content']}\n\n"
        filename = f"all_notes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        logger.info(f"Exported all notes to {filename}")
        return jsonify({'success': True, 'filename': filename, 'content': content})
    except Exception as e:
        logger.error(f"Error exporting all notes: {e}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/regenerate_all')
def regenerate_all():
    try:
        # Fetch all notes (excluding deleted ones)
        notes = get_all_notes()
        logger.info(f"Retrieved {len(notes)} notes for full regeneration")

        # Sort notes by creation time (newest first)
        notes.sort(key=lambda x: x['created_at'], reverse=True)

        # Build the initial document content from notes
        instructions = ""
        for note in notes:
            if note['is_deleted'] == 0:  # Only include non-deleted notes
                instructions += f"=== Added: {note['created_at']} ===\n"
                instructions += f"{note['content']}\n\n"

        # Run Revisor to generate the full document
        revisor = Revisor()
        logger.info("Starting full document regeneration with Revisor")
        html_content = revisor.run(current_document="", instructions=instructions)

        # Save the new document version
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

        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"Saved new full document version {version_number} to {html_path}")
        except Exception as e:
            logger.error(f"Failed to save full document to {html_path}: {e}")
            raise

        # Save to history
        conn = sqlite3.connect(Config.DATABASE)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO document_history (version_number, timestamp, html_content, diff_with_previous)
                VALUES (?, ?, ?, ?)
            ''', (version_number, timestamp, html_content, ""))
            conn.commit()
            logger.info(f"Saved full document history entry for version {version_number}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to save full document history: {e}")
            raise
        finally:
            conn.close()

        # Send email notification
        if Config.SMTP_ENABLED and Config.EMAIL_SENDER and Config.EMAIL_RECIPIENTS:
            try:
                send_email_notification(version_number, html_path)
            except Exception as e:
                logger.error(f"Failed to send email notification: {e}")

        return jsonify({'success': True, 'message': f'Full document regenerated with version {version_number}'})
    except Exception as e:
        logger.error(f"Error regenerating document: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/notes')
def api_notes():
    try:
        notes = get_all_notes()
        logger.info(f"Served API request for {len(notes)} notes")
        return jsonify(notes)
    except Exception as e:
        logger.error(f"Error in API notes endpoint: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/history')
def api_history():
    try:
        history = get_document_history()
        logger.info(f"Served API request for {len(history)} history entries")
        return jsonify(history)
    except Exception as e:
        logger.error(f"Error in API history endpoint: {e}")
        return jsonify({'error': str(e)}), 500

def open_browser():
    try:
        webbrowser.open_new("http://127.0.0.1:5983")
        logger.info("Browser opened successfully")
    except Exception as e:
        logger.error(f"Failed to open browser: {e}")

init_db()

if __name__ == '__main__':
    try:
        logger.info("Starting Flask application")
        app.run(host="0.0.0.0", port="5983", debug=Config.DEBUG)
    except Exception as e:
        logger.critical(f"Failed to start Flask application: {e}")
        raise