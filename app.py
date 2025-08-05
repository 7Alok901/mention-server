from flask import Flask, render_template, request, jsonify, send_file
import requests
import os
import time
import random
import threading
import json
from datetime import datetime
from requests.exceptions import RequestException
from werkzeug.utils import secure_filename
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables to track automation status
automation_status = {
    'running': False,
    'current_comment': 0,
    'total_comments': 0,
    'current_token': '',
    'current_post': '',
    'logs': []
}

class CommentAutomation:
    def __init__(self):
        self.stop_flag = False
        
    def log_message(self, message, level='info'):
        """Add log message to global status"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            'timestamp': timestamp,
            'message': message,
            'level': level
        }
        automation_status['logs'].append(log_entry)
        
        # Keep only last 100 logs to prevent memory issues
        if len(automation_status['logs']) > 100:
            automation_status['logs'] = automation_status['logs'][-100:]
            
        # Also log to file
        log_file = 'logs/app.log'
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} - {level.upper()}: {message}\n")

    def validate_token(self, token):
        """Validate Facebook token"""
        try:
            response = requests.get(f'https://graph.facebook.com/me?access_token={token}')
            data = response.json()
            
            if response.status_code == 200 and "name" in data:
                return True, data.get("name")
            return False, None
            
        except RequestException as e:
            self.log_message(f"Error validating token: {e}", 'error')
            return False, None

    def get_valid_tokens(self, tokens):
        """Get list of valid tokens"""
        valid_tokens = []
        for i, token in enumerate(tokens, 1):
            is_valid, name = self.validate_token(token.strip())
            if is_valid:
                valid_tokens.append({
                    'index': i,
                    'token': token.strip(),
                    'name': name
                })
                self.log_message(f"Valid token found: {name}")
            else:
                self.log_message(f"Invalid token #{i}", 'warning')
        
        return valid_tokens

    def post_comment(self, post_id, comment, token_info, mention_id=None, mention_name=None):
        """Post comment to Facebook"""
        try:
            # Format comment with mention if provided
            if mention_id and mention_name:
                formatted_comment = f"@[{mention_id}:{mention_name}] {comment}"
            else:
                formatted_comment = comment

            response = requests.post(
                f'https://graph.facebook.com/{post_id}/comments/',
                data={'message': formatted_comment, 'access_token': token_info['token']}
            )
            data = response.json()

            if 'id' in data:
                self.log_message(f"Comment posted successfully by {token_info['name']}")
                return True
            else:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                self.log_message(f"Failed to post comment: {error_msg}", 'error')
                return False

        except RequestException as e:
            self.log_message(f"Request error: {e}", 'error')
            return False

    def run_automation(self, tokens, comments, post_ids, delay, mention_id=None, mention_name=None):
        """Main automation function"""
        automation_status['running'] = True
        automation_status['total_comments'] = len(comments) * len(tokens) * len(post_ids)
        automation_status['current_comment'] = 0
        
        self.log_message("Starting comment automation...")
        
        valid_tokens = self.get_valid_tokens(tokens)
        if not valid_tokens:
            self.log_message("No valid tokens found", 'error')
            automation_status['running'] = False
            return

        comment_count = 0
        token_index = 0
        
        try:
            for comment_cycle in range(len(comments)):
                if self.stop_flag:
                    break
                    
                for post_id in post_ids:
                    if self.stop_flag:
                        break
                        
                    comment = comments[comment_cycle]
                    current_token = valid_tokens[token_index % len(valid_tokens)]
                    
                    automation_status['current_token'] = current_token['name']
                    automation_status['current_post'] = post_id
                    automation_status['current_comment'] = comment_count + 1
                    
                    self.log_message(f"Posting comment #{comment_count + 1}: '{comment}' to post {post_id}")
                    
                    success = self.post_comment(post_id, comment, current_token, mention_id, mention_name)
                    
                    if success:
                        comment_count += 1
                        # Random delay between comments
                        sleep_time = random.randint(delay, delay + 30)
                        self.log_message(f"Waiting {sleep_time} seconds before next comment...")
                        time.sleep(sleep_time)
                    
                    token_index += 1
                    
                    if self.stop_flag:
                        break
                        
        except Exception as e:
            self.log_message(f"Automation error: {e}", 'error')
        
        finally:
            automation_status['running'] = False
            self.log_message("Automation completed/stopped")

# Global automation instance
automation = CommentAutomation()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    """Handle file uploads"""
    try:
        uploaded_files = {}
        
        for file_type in ['tokens', 'comments']:
            if file_type in request.files:
                file = request.files[file_type]
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_type}_{filename}")
                    file.save(file_path)
                    
                    # Read file content
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = [line.strip() for line in f.readlines() if line.strip()]
                    
                    uploaded_files[file_type] = content
                    os.remove(file_path)  # Clean up uploaded file
        
        return jsonify({'success': True, 'files': uploaded_files})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/start_automation', methods=['POST'])
def start_automation():
    """Start the comment automation"""
    try:
        if automation_status['running']:
            return jsonify({'success': False, 'error': 'Automation is already running'})
        
        data = request.json
        
        tokens = data.get('tokens', [])
        comments = data.get('comments', [])
        post_ids = [pid.strip() for pid in data.get('post_ids', '').split(',') if pid.strip()]
        delay = max(60, int(data.get('delay', 60)))
        mention_id = data.get('mention_id', '').strip() or None
        mention_name = data.get('mention_name', '').strip() or None
        
        if not tokens or not comments or not post_ids:
            return jsonify({'success': False, 'error': 'Missing required data'})
        
        # Reset automation state
        automation.stop_flag = False
        automation_status['logs'] = []
        
        # Start automation in background thread
        thread = threading.Thread(
            target=automation.run_automation,
            args=(tokens, comments, post_ids, delay, mention_id, mention_name)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': 'Automation started'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop_automation', methods=['POST'])
def stop_automation():
    """Stop the automation"""
    automation.stop_flag = True
    automation_status['running'] = False
    automation.log_message("Automation stopped by user")
    return jsonify({'success': True, 'message': 'Automation stopped'})

@app.route('/status')
def get_status():
    """Get current automation status"""
    return jsonify(automation_status)

@app.route('/download_logs')
def download_logs():
    """Download log file"""
    log_file = 'logs/app.log'
    if os.path.exists(log_file):
        return send_file(log_file, as_attachment=True, download_name='automation_logs.txt')
    else:
        return jsonify({'error': 'No log file found'}), 404

@app.route('/health')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
