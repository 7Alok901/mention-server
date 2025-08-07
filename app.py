from flask import Flask, render_template, request, jsonify
import requests
import os
import time
import random
import threading
import uuid
from datetime import datetime
from requests.exceptions import RequestException
from werkzeug.utils import secure_filename
import logging

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Global dictionary to store running tasks
running_tasks = {}
task_stats = {}

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TaskRunner:
    def __init__(self, task_id, tokens, comments, post_id, delay_config, mention_config=None):
        self.task_id = task_id
        self.tokens = tokens
        self.comments = comments
        self.post_id = post_id
        self.delay_config = delay_config
        self.mention_config = mention_config
        self.is_running = True
        self.stats = {
            'started_at': datetime.now(),
            'comments_sent': 0,
            'errors': 0,
            'current_token': None,
            'current_comment': None
        }
        
    def validate_token(self, token):
        """Validate token and return user/page info if valid."""
        try:
            response = requests.get(f'https://graph.facebook.com/me?access_token={token}', timeout=10)
            data = response.json()
            
            if response.status_code == 200 and "name" in data:
                token_type = "page" if "category" in data else "profile"
                return token_type, data.get("name"), data.get("id")
            return None, None, None
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return None, None, None
    
    def get_delay(self):
        """Calculate delay based on delay configuration."""
        if self.delay_config['mode'] == 'random':
            return random.randint(self.delay_config['min'], self.delay_config['max'])
        else:  # accurate mode
            return random.choice(self.delay_config['values'])
    
    def post_comment(self, token_info, comment):
        """Post a comment using Facebook Graph API."""
        token_type, token_name, token_id, token = token_info
        
        # Format comment with mention if enabled
        formatted_comment = comment
        if self.mention_config and self.mention_config['enabled']:
            formatted_comment = f"@[{self.mention_config['id']}:{self.mention_config['name']}] {comment}"
        
        try:
            response = requests.post(
                f'https://graph.facebook.com/{self.post_id}/comments/',
                data={'message': formatted_comment, 'access_token': token},
                timeout=15
            )
            data = response.json()
            
            if 'id' in data:
                logger.info(f"Comment posted successfully by {token_name}")
                return True, "Success"
            else:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                logger.error(f"Failed to post comment: {error_msg}")
                return False, error_msg
                
        except Exception as e:
            logger.error(f"Request error: {e}")
            return False, str(e)
    
    def run(self):
        """Main task execution loop."""
        # Validate all tokens first
        valid_tokens = []
        for token in self.tokens:
            token_type, token_name, token_id = self.validate_token(token)
            if token_name:
                valid_tokens.append((token_type, token_name, token_id, token))
        
        if not valid_tokens:
            logger.error(f"No valid tokens found for task {self.task_id}")
            return
        
        logger.info(f"Task {self.task_id} started with {len(valid_tokens)} valid tokens")
        
        comment_index = 0
        token_index = 0
        
        while self.is_running:
            try:
                # Get current comment and token
                comment = self.comments[comment_index % len(self.comments)]
                token_info = valid_tokens[token_index % len(valid_tokens)]
                
                # Update current status
                self.stats['current_token'] = f"{token_info[1]} ({token_info[0]})"
                self.stats['current_comment'] = comment[:50] + "..." if len(comment) > 50 else comment
                
                # Post comment
                success, message = self.post_comment(token_info, comment)
                
                if success:
                    self.stats['comments_sent'] += 1
                else:
                    self.stats['errors'] += 1
                
                # Move to next token and comment
                token_index = (token_index + 1) % len(valid_tokens)
                comment_index += 1
                
                # Wait for delay
                if self.is_running:
                    delay = self.get_delay()
                    time.sleep(delay)
                
            except Exception as e:
                logger.error(f"Error in task {self.task_id}: {e}")
                self.stats['errors'] += 1
                time.sleep(5)  # Short delay before continuing
    
    def stop(self):
        """Stop the task."""
        self.is_running = False
        logger.info(f"Task {self.task_id} stopped")

def read_file_lines(filepath):
    """Read lines from a file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            return [line.strip() for line in file.readlines() if line.strip()]
    except Exception as e:
        logger.error(f"Error reading file {filepath}: {e}")
        return []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    """Handle file uploads."""
    try:
        uploaded_files = {}
        
        for file_type in ['tokens', 'comments']:
            if file_type in request.files:
                file = request.files[file_type]
                if file and file.filename:
                    filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    uploaded_files[file_type] = filepath
        
        return jsonify({'success': True, 'files': uploaded_files})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/start_task', methods=['POST'])
def start_task():
    """Start a new comment automation task."""
    try:
        data = request.json
        
        # Generate unique task ID
        task_id = str(uuid.uuid4())[:8]
        
        # Read tokens and comments from uploaded files
        tokens = read_file_lines(data['token_file'])
        comments = read_file_lines(data['comment_file'])
        
        if not tokens:
            return jsonify({'success': False, 'error': 'No tokens found in file'})
        
        if not comments:
            return jsonify({'success': False, 'error': 'No comments found in file'})
        
        # Parse delay configuration
        delay_config = data['delay_config']
        if delay_config['mode'] == 'accurate':
            try:
                delay_config['values'] = [int(x.strip()) for x in delay_config['values'].split(',')]
            except ValueError:
                return jsonify({'success': False, 'error': 'Invalid delay values format'})
        
        # Parse mention configuration
        mention_config = None
        if data.get('mention_enabled'):
            mention_config = {
                'enabled': True,
                'id': data['mention_id'],
                'name': data['mention_name']
            }
        
        # Create and start task
        task = TaskRunner(
            task_id=task_id,
            tokens=tokens,
            comments=comments,
            post_id=data['post_id'],
            delay_config=delay_config,
            mention_config=mention_config
        )
        
        # Start task in background thread
        thread = threading.Thread(target=task.run, daemon=True)
        thread.start()
        
        # Store task reference
        running_tasks[task_id] = task
        task_stats[task_id] = task.stats
        
        logger.info(f"Started task {task_id}")
        
        return jsonify({
            'success': True, 
            'task_id': task_id,
            'message': f'Task started with ID: {task_id}'
        })
        
    except Exception as e:
        logger.error(f"Error starting task: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop_task', methods=['POST'])
def stop_task():
    """Stop a running task."""
    try:
        data = request.json
        task_id = data.get('task_id')
        
        if task_id not in running_tasks:
            return jsonify({'success': False, 'error': 'Task not found or already stopped'})
        
        # Stop the task
        running_tasks[task_id].stop()
        del running_tasks[task_id]
        
        logger.info(f"Stopped task {task_id}")
        
        return jsonify({'success': True, 'message': f'Task {task_id} stopped successfully'})
        
    except Exception as e:
        logger.error(f"Error stopping task: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/task_status/<task_id>')
def get_task_status(task_id):
    """Get status of a specific task."""
    if task_id in running_tasks:
        stats = running_tasks[task_id].stats
        stats['status'] = 'running'
        return jsonify({'success': True, 'stats': stats})
    elif task_id in task_stats:
        stats = task_stats[task_id]
        stats['status'] = 'stopped'
        return jsonify({'success': True, 'stats': stats})
    else:
        return jsonify({'success': False, 'error': 'Task not found'})

@app.route('/running_tasks')
def get_running_tasks():
    """Get list of all running tasks."""
    tasks = []
    for task_id, task in running_tasks.items():
        tasks.append({
            'task_id': task_id,
            'stats': task.stats
        })
    return jsonify({'success': True, 'tasks': tasks})

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'File too large. Maximum size is 16MB.'}), 413

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
