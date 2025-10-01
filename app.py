"""
Brain Dump - A Flask application for managing and organizing notes with LLM-powered structuring
MIT License - Copyright (c) 2025 Daniel Sweetser
"""

import os
import sqlite3
import hashlib
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from pathlib import Path

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this in production

# Configuration
DATABASE = 'brain_dump.db'
NOTE_DIR = 'notes'
HTML_OUTPUT = 'output'
PDF_OUTPUT = 'pdf'
SYSTEM_PROMPT_FILE = 'system_prompt.txt'

# Create directories if they don't exist
for directory in [NOTE_DIR, HTML_OUTPUT, PDF_OUTPUT]:
    Path(directory).mkdir(exist_ok=True)

# Initialize database
def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Create notes table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hash TEXT UNIQUE NOT NULL
        )
    ''')
    
    # Create history table for document versions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_number INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            html_content TEXT NOT NULL,
            pdf_path TEXT,
            diff_with_previous TEXT
        )
    ''')
    
    # Create system prompt table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_prompt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL
        )
    ''')
    
    # Initialize with default system prompt if none exists
    cursor.execute('SELECT COUNT(*) FROM system_prompt')
    if cursor.fetchone()[0] == 0:
        default_prompt = """
You are a professional note organizer and knowledge architect. Your task is to take a collection of raw notes and organize them into a coherent, well-structured, and navigable document.
 
Guidelines:
1. Create a comprehensive table of contents with appropriate headings and subheadings
2. Group related notes together thematically
3. Use clear and descriptive section titles
4. Preserve all information from the original notes
5. Create meaningful links between related sections
6. Use markdown formatting for the final output
7. Ensure the document is easy to navigate and understand
8. Maintain the original meaning and intent of the notes
9. Add any relevant context or connections between ideas
10. Use clear and concise language
"""
        cursor.execute('INSERT INTO system_prompt (prompt) VALUES (?)', (default_prompt,))
    
    conn.commit()
    conn.close()

# Get system prompt
def get_system_prompt():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT prompt FROM system_prompt LIMIT 1')
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0]
    return ""

# Save system prompt
def save_system_prompt(prompt):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM system_prompt')
    cursor.execute('INSERT INTO system_prompt (prompt) VALUES (?)', (prompt,))
    conn.commit()
    conn.close()

# Generate note hash for deduplication
def generate_note_hash(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

# Save note to database
def save_note(title, content):
    note_hash = generate_note_hash(content)
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO notes (title, content, hash)
            VALUES (?, ?, ?)
        ''', (title, content, note_hash))
        
        note_id = cursor.lastrowid
        conn.commit()
        
        # After saving a new note, trigger document regeneration
        regenerate_document()
        
        return note_id
    except sqlite3.IntegrityError:
        # Note with this hash already exists
        conn.rollback()
        conn.close()
        return None
    finally:
        conn.close()

# Get all notes
def get_all_notes():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, title, content, created_at FROM notes ORDER BY created_at DESC')
    notes = cursor.fetchall()
    conn.close()
    
    # Convert to list of dictionaries
    return [
        {
            'id': note[0],
            'title': note[1],
            'content': note[2],
            'created_at': note[3]
        }
        for note in notes
    ]

# Get document history
def get_document_history():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, version_number, timestamp, html_content, pdf_path, diff_with_previous FROM document_history ORDER BY timestamp DESC')
    history = cursor.fetchall()
    conn.close()
    
    return [
        {
            'id': item[0],
            'version_number': item[1],
            'timestamp': item[2],
            'html_content': item[3],
            'pdf_path': item[4],
            'diff_with_previous': item[5]
        }
        for item in history
    ]

# Regenerate the document using the LLM (stub function)
def regenerate_document():
    # This is where you would call your LLM API
    # For now, we'll create a simple placeholder implementation
    notes = get_all_notes()
    
    if not notes:
        return
    
    # Create a simple HTML document with a table of contents
    # In a real implementation, this would be generated by your LLM
    html_content = generate_html_document(notes)
    
    # Get the latest version number
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(version_number) FROM document_history')
    result = cursor.fetchone()
    conn.close()
    
    version_number = (result[0] or 0) + 1
    
    # Generate a diff with the previous version if it exists
    diff_content = ""
    if version_number > 1:
        # For now, just create a simple diff placeholder
        diff_content = f"Version {version_number} includes new notes and structural updates."
    
    # Save to database
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Generate a unique filename for this version
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_filename = f"brain_dump_v{version_number}_{timestamp}.pdf"
    pdf_path = os.path.join(PDF_OUTPUT, pdf_filename)
    
    # Save HTML content
    html_filename = f"brain_dump_v{version_number}_{timestamp}.html"
    html_path = os.path.join(HTML_OUTPUT, html_filename)
    
    # Write HTML file
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # Save to database
    cursor.execute('''
        INSERT INTO document_history (version_number, html_content, pdf_path, diff_with_previous)
        VALUES (?, ?, ?, ?)
    ''', (version_number, html_content, pdf_path, diff_content))
    
    conn.commit()
    conn.close()
    
    # Generate PDF (stub - in a real implementation, use weasyprint or similar)
    generate_pdf(html_path, pdf_path)

# Generate HTML document from notes (stub function)
def generate_html_document(notes):
    # In a real implementation, this would be generated by your LLM
    # For now, we'll create a simple HTML document
    
    # Create a simple table of contents
    toc_items = []
    for i, note in enumerate(notes):
        # Use the first few words of the title as the TOC entry
        title = note['title']
        if len(title) > 30:
            title = title[:27] + "..."
        
        # Create a unique ID for the section
        section_id = f"note-{i+1}"
        toc_items.append(f'<li><a href="#{section_id}">{title}</a></li>')
    
    # Create the HTML content
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Brain Dump - Organized Notes</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        header {{
            text-align: center;
            margin-bottom: 40px;
            border-bottom: 1px solid #eee;
            padding-bottom: 20px;
        }}
        h1 {{
            color: #2c3e50;
        }}
        .toc {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
        }}
        .toc h2 {{
            margin-top: 0;
            color: #3498db;
            border-bottom: 1px solid #ddd;
            padding-bottom: 10px;
        }}
        .toc ul {{
            list-style-type: none;
            padding-left: 0;
        }}
        .toc li {{
            margin-bottom: 8px;
        }}
        .toc a {{
            color: #3498db;
            text-decoration: none;
            transition: color 0.3s;
        }}
        .toc a:hover {{
            color: #2980b9;
            text-decoration: underline;
        }}
        .note {{
            margin-bottom: 40px;
            padding: 20px;
            background-color: #ffffff;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .note h2 {{
            margin-top: 0;
            color: #2c3e50;
            border-bottom: 1px solid #eee;
            padding-bottom: 10px;
        }}
        .note .content {{
            margin-top: 15px;
        }}
        .note .metadata {{
            font-size: 0.8em;
            color: #666;
            margin-top: 10px;
        }}
        footer {{
            text-align: center;
            margin-top: 60px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            color: #999;
            font-size: 0.9em;
        }}
        .diff {{
            background-color: #fff3cd;
            border: 1px solid #ffeaa7;
            border-radius: 4px;
            padding: 10px;
            margin: 15px 0;
            font-size: 0.9em;
        }}
        .diff strong {{
            color: #856404;
        }}
    </style>
</head>
<body>
    <header>
        <h1>Brain Dump - Organized Notes</h1>
        <p>Automatically generated from your raw notes using AI</p>
    </header>
    
    <div class="toc">
        <h2>Table of Contents</h2>
        <ul>
            {"".join(toc_items)}
        </ul>
    </div>
    
    <div class="diff">
        <strong>Version {get_latest_version_number()}</strong>: 
        This document was automatically generated from {len(notes)} notes.
    </div>
    
    {"".join(generate_note_html(note, i+1) for i, note in enumerate(notes))}
    
    <footer>
        <p>Brain Dump - MIT License (c) 2025 Daniel Sweetser</p>
        <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </footer>
</body>
</html>
    """
    
    return html_content

# Generate HTML for a single note
def generate_note_html(note, index):
    # Use the first 100 characters of the content as preview
    preview = note['content'][:100]
    if len(note['content']) > 100:
        preview += "..."
    
    # Create a unique ID for this note
    section_id = f"note-{index}"
    
    # Use markdown for code blocks
    content_html = note['content']
    
    # Simple markdown processing for code blocks
    content_html = content_html.replace('```', '<pre><code>')
    content_html = content_html.replace('```', '</code></pre>')
    
    return f"""
    <div class="note" id="{section_id}">
        <h2>{note['title']}</h2>
        <div class="content">
            {content_html}
        </div>
        <div class="metadata">
            Added on {note['created_at']} | Note {index}
        </div>
    </div>
    """

# Get the latest version number
def get_latest_version_number():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(version_number) FROM document_history')
    result = cursor.fetchone()
    conn.close()
    
    return result[0] or 0

# Generate PDF from HTML (stub function)
def generate_pdf(html_path, pdf_path):
    # In a real implementation, you would use a library like weasyprint
    # For now, we'll just create an empty PDF file
    # This is a placeholder - you would need to implement actual PDF generation
    try:
        # This is a placeholder. In a real implementation, you would use:
        # from weasyprint import HTML
        # HTML(html_path).write_pdf(pdf_path)
        pass
    except Exception as e:
        print(f"Error generating PDF: {e}")
        # Create an empty PDF file as fallback
        with open(pdf_path, 'w') as f:
            f.write("PDF generation failed - this is a placeholder")

# Routes
@app.route('/')
def index():
    notes = get_all_notes()
    history = get_document_history()
    
    # Get the latest document version
    latest_version = None
    if history:
        latest_version = history[0]
    
    # Get system prompt
    system_prompt = get_system_prompt()
    
    return render_template('index.html', 
                         notes=notes, 
                         history=history, 
                         latest_version=latest_version,
                         system_prompt=system_prompt)

@app.route('/add_note', methods=['POST'])
def add_note():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    
    if not title or not content:
        return jsonify({'error': 'Title and content are required'}), 400
    
    note_id = save_note(title, content)
    
    if note_id is None:
        return jsonify({'error': 'Note with this content already exists'}), 400
    
    return jsonify({'success': True, 'message': 'Note added successfully', 'note_id': note_id})

@app.route('/delete_note/<int:note_id>', methods=['POST'])
def delete_note(note_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        # First, get the note to delete
        cursor.execute('SELECT content FROM notes WHERE id = ?', (note_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return jsonify({'error': 'Note not found'}), 404
        
        # Delete the note
        cursor.execute('DELETE FROM notes WHERE id = ?', (note_id,))
        
        # If any notes were deleted
        if cursor.rowcount > 0:
            # After deleting a note, trigger document regeneration
            regenerate_document()
            conn.commit()
            return jsonify({'success': True, 'message': 'Note deleted successfully'})
        else:
            conn.rollback()
            return jsonify({'error': 'Note not found'}), 404
            
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/edit_note/<int:note_id>', methods=['POST'])
def edit_note(note_id):
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    
    if not title or not content:
        return jsonify({'error': 'Title and content are required'}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        # Check if note exists
        cursor.execute('SELECT id FROM notes WHERE id = ?', (note_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Note not found'}), 404
        
        # Update the note
        cursor.execute('''
            UPDATE notes 
            SET title = ?, content = ? 
            WHERE id = ?
        ''', (title, content, note_id))
        
        # After updating, trigger document regeneration
        regenerate_document()
        conn.commit()
        
        return jsonify({'success': True, 'message': 'Note updated successfully'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/system_prompt', methods=['POST'])
def update_system_prompt():
    prompt = request.form.get('prompt', '').strip()
    
    if not prompt:
        return jsonify({'error': 'System prompt cannot be empty'}), 400
    
    save_system_prompt(prompt)
    
    return jsonify({'success': True, 'message': 'System prompt updated successfully'})

@app.route('/export_html/<int:version_id>')
def export_html(version_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT html_content, timestamp FROM document_history WHERE id = ?', (version_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return jsonify({'error': 'Version not found'}), 404
    
    html_content, timestamp = result
    
    # Create a filename with timestamp
    filename = f"brain_dump_v{version_id}_{timestamp}.html"
    
    # Return the HTML content as a downloadable file
    return jsonify({
        'success': True,
        'filename': filename,
        'content': html_content
    })

@app.route('/export_pdf/<int:version_id>')
def export_pdf(version_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT pdf_path FROM document_history WHERE id = ?', (version_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return jsonify({'error': 'Version not found'}), 404
    
    pdf_path = result[0]
    
    # Check if the PDF file exists
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'PDF file not found'}), 404
    
    # Return the PDF file for download
    return send_file(pdf_path, as_attachment=True)

@app.route('/export_all_notes')
def export_all_notes():
    notes = get_all_notes()
    
    # Create a simple text file with all notes
    content = ""
    for note in notes:
        content += f"=== {note['title']} ===\n"
        content += f"Added: {note['created_at']}\n"
        content += f"{note['content']}\n\n"
    
    filename = f"all_notes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    return jsonify({
        'success': True,
        'filename': filename,
        'content': content
    })

@app.route('/api/notes')
def api_notes():
    notes = get_all_notes()
    return jsonify(notes)

@app.route('/api/history')
def api_history():
    history = get_document_history()
    return jsonify(history)

@app.route('/api/system_prompt')
def api_system_prompt():
    prompt = get_system_prompt()
    return jsonify({'prompt': prompt})

if __name__ == '__main__':
    # Initialize the database
    init_db()
    
    # Run the Flask app
    app.run(debug=True)