from flask import Flask, render_template, request, jsonify, send_file
import requests
import os
import time
import random
import threading
import json
import uuid
from datetime import datetime
from requests.exceptions import RequestException
from werkzeug.utils import secure_filename
import logging

app = Flask(_name_)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(_name_)

# Global variables to track automation status with task management
automation_status = {
    'running': False,
    'current_comment': 0,
    'total_comments': 0,
    'current_token': '',
    'current_post': '',
    'task_id': None,
    'start_time': None,
    'logs': []
}

# Dictionary to store active tasks
active_tasks = {}

class CommentAutomation:
    def _init_(self):
        self.active_task_id = None
        
    def log_message(self, message, level='info', task_id=None):
        """Add log message to global status"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            'timestamp': timestamp,
            'message': message,
            'level': level,
            'task_id': task_id or self.active_task_id
        }
        automation_status['logs'].append(log_entry)
        
        # Keep only last 200 logs to prevent memory issues
        if len(automation_status['logs']) > 200:
            automation_status['logs'] = automation_status['logs'][-200:]
            
        # Also log to file
        log_file = 'logs/app.log'
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} - {level.upper()} - Task:{task_id or self.active_task_id}: {message}\n")

    def generate_task_id(self):
        """Generate unique task ID"""
        return str(uuid.uuid4())[:8]

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

    def is_task_stopped(self, task_id):
        """Check if task should be stopped"""
        return task_id not in active_tasks or active_tasks[task_id].get('stop_flag', False)

    def run_automation(self, task_id, tokens, comments, post_ids, delay, mention_id=None, mention_name=None):
        """Main automation function with infinite loop until stopped by task ID"""
        self.active_task_id = task_id
        
        automation_status['running'] = True
        automation_status['task_id'] = task_id
        automation_status['start_time'] = datetime.now().isoformat()
        automation_status['current_comment'] = 0
        
        self.log_message(f"Starting infinite comment automation with Task ID: {task_id}")
        
        valid_tokens = self.get_valid_tokens(tokens)
        if not valid_tokens:
            self.log_message("No valid tokens found", 'error')
            automation_status['running'] = False
            if task_id in active_tasks:
                del active_tasks[task_id]
            return

        comment_count = 0
        token_index = 0
        cycle_count = 0
        
        try:
            # Infinite loop - will only stop when task is manually stopped
            while task_id in active_tasks and not self.is_task_stopped(task_id):
                cycle_count += 1
                self.log_message(f"Starting cycle #{cycle_count}")
                
                for comment_index, comment in enumerate(comments):
                    if self.is_task_stopped(task_id):
                        break
                        
                    for post_id in post_ids:
                        if self.is_task_stopped(task_id):
                            break
                            
                        current_token = valid_tokens[token_index % len(valid_tokens)]
                        
                        automation_status['current_token'] = current_token['name']
                        automation_status['current_post'] = post_id
                        automation_status['current_comment'] = comment_count + 1
                        
                        self.log_message(f"Cycle {cycle_count} - Comment #{comment_count + 1}: '{comment}' to post {post_id}")
                        
                        success = self.post_comment(post_id, comment, current_token, mention_id, mention_name)
                        
                        if success:
                            comment_count += 1
                            # Update task info
                            if task_id in active_tasks:
                                active_tasks[task_id]['comments_posted'] = comment_count
                        
                        # Random delay between comments
                        sleep_time = random.randint(delay, delay + 30)
                        self.log_message(f"Waiting {sleep_time} seconds before next comment...")
                        
                        # Sleep in small intervals to check for stop signal
                        for _ in range(sleep_time):
                            if self.is_task_stopped(task_id):
                                break
                            time.sleep(1)
                        
                        token_index += 1
                        
                        if self.is_task_stopped(task_id):
                            break
                    
                    if self.is_task_stopped(task_id):
                        break
                
                # Small delay between cycles
                if not self.is_task_stopped(task_id):
                    self.log_message(f"Cycle {cycle_count} completed. Starting next cycle in 60 seconds...")
                    for _ in range(60):
                        if self.is_task_stopped(task_id):
                            break
                        time.sleep(1)
                        
        except Exception as e:
            self.log_message(f"Automation error: {e}", 'error')
        
        finally:
            # Clean up
            automation_status['running'] = False
            automation_status['task_id'] = None
            if task_id in active_tasks:
                active_tasks[task_id]['status'] = 'completed'
                active_tasks[task_id]['end_time'] = datetime.now().isoformat()
            self.log_message(f"Automation with Task ID {task_id} completed/stopped. Total comments posted: {comment_count}")

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
    """Start the comment automation with task ID"""
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
        
        # Generate unique task ID
        task_id = automation.generate_task_id()
        
        # Store task information
        active_tasks[task_id] = {
            'id': task_id,
            'status': 'running',
            'start_time': datetime.now().isoformat(),
            'tokens_count': len(tokens),
            'comments_count': len(comments),
            'post_ids_count': len(post_ids),
            'comments_posted': 0,
            'stop_flag': False
        }
        
        # Reset automation state
        automation_status['logs'] = []
        
        # Start automation in background thread
        thread = threading.Thread(
            target=automation.run_automation,
            args=(task_id, tokens, comments, post_ids, delay, mention_id, mention_name)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True, 
            'message': 'Automation started', 
            'task_id': task_id,
            'note': 'This automation will run infinitely until stopped using the task ID'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop_automation', methods=['POST'])
def stop_automation():
    """Stop the automation using task ID"""
    try:
        data = request.json
        task_id = data.get('task_id')
        
        if not task_id:
            return jsonify({'success': False, 'error': 'Task ID is required'})
        
        if task_id not in active_tasks:
            return jsonify({'success': False, 'error': 'Invalid or expired task ID'})
        
        # Set stop flag for the specific task
        active_tasks[task_id]['stop_flag'] = True
        active_tasks[task_id]['status'] = 'stopping'
        
        automation.log_message(f"Stop signal sent for Task ID: {task_id}", 'info', task_id)
        
        return jsonify({'success': True, 'message': f'Stop signal sent for task {task_id}'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/status')
def get_status():
    """Get current automation status"""
    status_with_tasks = automation_status.copy()
    status_with_tasks['active_tasks'] = active_tasks
    return jsonify(status_with_tasks)

@app.route('/tasks')
def get_tasks():
    """Get all tasks (active and completed)"""
    return jsonify({'tasks': active_tasks})

@app.route('/task/<task_id>')
def get_task_info(task_id):
    """Get specific task information"""
    if task_id not in active_tasks:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify({'task': active_tasks[task_id]})

@app.route('/clear_completed_tasks', methods=['POST'])
def clear_completed_tasks():
    """Clear completed/stopped tasks from memory"""
    global active_tasks
    active_tasks = {k: v for k, v in active_tasks.items() if v['status'] == 'running'}
    return jsonify({'success': True, 'message': 'Completed tasks cleared'})

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

if _name_ == '_main_':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
